"""PlanningWorker：预算、每日行程编排、时间校验。

使用 ReAct（思考-行动-观察）循环 默认最多 4 轮迭代。
作用：调用任何工具，读取上游 research_result（景点）+logistics_result
（天气 / 酒店 / 路线 / 美食 / 往返返程），LLM 编排输出结构化 JSON 行程；
支持多套对比方案（1‑3 套）、逐代迭代优化、指标计算、LangFuse 指标上报、JSON
 自动修复、兜底降级。属于 LangGraph 节点，执行完成后，固定边回到 supervisor，
 本节点内部不做调度决策，不修改 retry_count、next_worker，全部交给 supervisor 流转到 Critic 做质量校验。

 supervisor
    ↓research → supervisor
    ↓logistics → supervisor
    ↓planning → supervisor
    ↓critic
        pass → END
        fail → supervisor（读取review_feedback，选择重做哪个worker）

"""

import copy
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ...agent_graph.state import AgentState
from ...agent_graph.json_utils import extract_json, normalize_plan_days
from ..config.constant import PLANNING_SYSTEM_PROMPT, MAX_RESULT_LENGTH, PLAN_VARIANT_DIRECTIVES
from ...constants import (
    PLAN_TYPES, DEFAULT_PLAN_TYPE, PLANNING_JSON_MODE,
    DEFAULT_PLAN_COUNT, MIN_PLAN_COUNT, MAX_PLAN_COUNT,
)
from ...agent_graph.llm_errors import is_content_filter_error
from ..plan_metrics import relabel_plan_variants, compute_plan_metrics
from ..plan_schema import validate_plan_structure
import logging

logger = logging.getLogger(__name__)
PLANNING_SYSTEM_PROMPT = PLANNING_SYSTEM_PROMPT

# ---------- 多方案逐代优化：LangFuse 用量反馈辅助 ----------
# 说明：方案不再绑定固定方向（省时/省钱/性价比），改为顺序生成，每个后续方案基于
# 前序方案的真实指标（通勤/花费）与 LLM token 用量构造「拉向更优」的反馈，
# 让后生成的方案在前序基础上进一步优化；并把每代指标与 token 用量上报 LangFuse 做对比。

_langfuse_client = None


def _get_langfuse_client():
    """懒加载 LangFuse 单例客户端；未安装/未配置时返回 None，绝不影响行程生成。"""
    global _langfuse_client
    if _langfuse_client is None:
        try:
            from langfuse import Langfuse
            _langfuse_client = Langfuse()
        except Exception as exc:
            _langfuse_client = False
            logger.warning("LangFuse 未就绪，跳过方案用量对比上报: %s", exc)
    return _langfuse_client or None


def _record_variant_langfuse(model_name: str, plan_type: str, plan: dict, metrics: dict, usage: dict) -> None:
    """单个方案的指标与 token 用量上报 LangFuse，用于三方案对比看板；失败不影响主流程。"""
    client = _get_langfuse_client()
    if not client:
        return
    try:
        client.generation(
            name="planning_variant_" + plan_type,
            model=model_name,
            input=json.dumps({"plan_type": plan_type}, ensure_ascii=False),
            output=json.dumps({"plan_type": plan_type, "metrics": metrics}, ensure_ascii=False),
            usage={
                "input": (usage or {}).get("input_tokens") or 0,
                "output": (usage or {}).get("output_tokens") or 0,
                "total": (usage or {}).get("total_tokens") or 0,
            },
            metadata={
                "commute_minutes": metrics.get("commute_minutes", 0),
                "total_cost": metrics.get("total_cost", 0),
                "day_count": metrics.get("day_count", 0),
            },
        )
    except Exception as exc:
        logger.debug("LangFuse 记录方案[%s]失败: %s", plan_type, exc)


def _build_prior_feedback(prior_records: list, variant_type: str) -> str:
    """基于前序已生成方案的真实指标与 token 用量，构造「拉向更优」的优化反馈。

    - 无前序方案：给出通用最优方向（短通勤、低花费、节奏合理）。
    - 有前序方案：列出每个前序方案的指标与 token 用量，要求本方案进一步更优。
    """
    plan_name = PLAN_TYPES.get(variant_type, {}).get("name", variant_type)
    if not prior_records:
        return ("方案优化方向（{name}）：请产出一套整体最优的完整行程，"
                "在保证可行与节奏合理的前提下，尽量缩短总通勤时间、降低总花费。").format(name=plan_name)
    lines = ["方案优化方向（{name}）：请参考已生成的前序方案，进一步优化使其更优（更短通勤、更低花费、更合理的节奏）。".format(name=plan_name)]
    for i, rec in enumerate(prior_records, 1):
        m = rec["metrics"]
        usage = rec.get("usage") or {}
        tok = usage.get("total_tokens") or ""
        prev_name = PLAN_TYPES.get(rec["plan_type"], {}).get("name", rec["plan_type"])
        lines.append(
            "- 前序方案[{prev}]：总通勤约{c}分钟、总花费约¥{cost}、{days}天；LLM tokens={tok}。".format(
                prev=prev_name, c=m["commute_minutes"], cost=m["total_cost"], days=m["day_count"], tok=tok
            )
        )
    lines.append("请在以上前序方案基础上，使本方案在总通勤和总花费上更优，且行程依然完整可行。")
    return "\n".join(lines)



def _validate_plan_schema(plan: dict) -> None:
    """校验行程JSON必填顶层字段，防止模型输出与行程无关的示例JSON（如 {"name":"John",...}）。

    Raises:
        ValueError: 缺少必填字段或 days 为空。
    """
    # 委托 Pydantic 容错层做结构化校验（必填字段 + 类型规整）
    validate_plan_structure(plan)




def _build_fallback_plan(city, city_list, origin, start_date, end_date, travel_days, transportation, accommodation):
    """构造最小可用兜底行程（LLM连续失败时保证至少返回一个方案，避免整个任务中止）。"""
    days = []
    base_date = None
    if start_date:
        try:
            from datetime import datetime, timedelta
            base_date = datetime.strptime(start_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            base_date = None
    for idx in range(max(int(travel_days or 1), 1)):
        city_name = (city_list[0]["city_name"] if city_list and len(city_list) > 0 else city) or city or ""
        day = {
            "city_name": city_name,
            "date": (base_date + timedelta(days=idx)).strftime("%Y-%m-%d") if base_date else "",
            "day_index": idx,
            "description": "LLM服务暂不可用，当前为基础兜底行程框架，可重新生成获取完整方案",
            "transportation": transportation or "公共交通",
            "accommodation": accommodation or "经济型酒店",
            "attractions": [],
            "meals": [
                {"type": "breakfast", "name": "早餐", "description": "", "estimated_cost": 30},
                {"type": "lunch", "name": "午餐", "description": "", "estimated_cost": 50},
                {"type": "dinner", "name": "晚餐", "description": "", "estimated_cost": 80},
            ],
        }
        days.append(day)
    fallback = {
        "city": city,
        "city_list": city_list or None,
        "origin": origin or "",
        "start_date": start_date or "",
        "end_date": end_date or "",
        "days": days,
        "weather_info": [],
        "overall_suggestions": "LLM服务暂不可用，已生成基础兜底行程。请稍后重试获取完整方案。",
        "budget": {
            "total_attractions": 0,
            "total_hotels": 0,
            "total_meals": sum(160 for _ in days),
            "total_transportation": 50 * len(days),
            "total": sum(160 for _ in days) + 50 * len(days),
        },
    }
    return fallback

def create_planning_worker(llm: ChatOpenAI):
    """
    创建 PlanningWorker 节点工厂函数
    :param llm: 注入大模型实例
    :return: planning_node，LangGraph可注册的异步节点函数
    """

    async def planning_node(state: AgentState) -> dict:
        """
        LangGraph节点：整合研究、后勤两份结果，编排完整行程JSON
        :param state: AgentState 全局状态
        :return: dict 更新AgentState的planning_result字段
        """
        city = state.get("city", "")
        city_list = state.get("city_list")
        start_date = state.get("start_date", "")
        end_date = state.get("end_date", "")
        travel_days = state.get("travel_days", 1)
        transportation = state.get("transportation", "公共交通")
        accommodation = state.get("accommodation", "经济型酒店")
        preferences = state.get("preferences", [])
        # 新增：出发地、成人/儿童人数、方案类型
        origin = state.get("origin", "") or ""
        adults = state.get("adults", 1) or 1
        children = state.get("children", 0) or 0
        plan_type = state.get("plan_type", "") or DEFAULT_PLAN_TYPE
        if plan_type not in PLAN_TYPES:
            plan_type = DEFAULT_PLAN_TYPE
        # ResearchWorker输出：景点信息，兼容None
        research_result = state.get("research_result") or ""
        # LogisticsWorker输出：后勤信息，兼容None
        logistics_result = state.get("logistics_result") or ""

        # =========组装城市描述=========
        if city_list is not None and len(city_list) > 0:
            city_parts = []
            day_index = 1
            daily_city_lines = []
            for item in city_list:
                c_name = item["city_name"]
                stay_days = item["stay_days"]
                city_parts.append(f"【{c_name}】停留 {stay_days} 天")
                daily_city_lines.append(f"第{day_index}天 ~ 第{day_index + stay_days - 1}天：{c_name}")
                day_index += stay_days
            city_desc = "本次为多城市旅行：\n" + "\n".join(city_parts)
            city_desc += "\n\n每日城市分配：\n" + "\n".join(daily_city_lines)
            city_desc += "\n\n务必根据上述城市分配安排每天行程，每天必须在对应城市内安排景点。"
        else:
            city_desc = f"目的地城市：{city}"

        # 读取方案数量：默认3个，限制在1-3之间
        try:
            plan_count = int(state.get("plan_count", DEFAULT_PLAN_COUNT) or DEFAULT_PLAN_COUNT)
        except (TypeError, ValueError):
            plan_count = DEFAULT_PLAN_COUNT
        plan_count = max(MIN_PLAN_COUNT, min(plan_count, MAX_PLAN_COUNT))

        logger.info(f"PlanningWorker 开始编排行程 {city_desc}, travel_days={travel_days}, plan_type={plan_type}, plan_count={plan_count}")

        # 参数校验：多城市存在city_list放行；单城市校验city非空
        if (city_list is None or len(city_list) == 0) and not city.strip() or travel_days <= 0:
            logger.warning("PlanningWorker 参数非法，终止编排")
            err_msg = "错误：目的地城市或旅行天数参数异常，无法生成行程。"
            return {
                "planning_result": err_msg,
                "planning_json_broken": True
            }

        # ========== 组装基础用户消息（三方案共享） ==========
        # 携带出发地、出行人员信息；children>0时加入儿童友好约束；注明启程/返程计入旅行天数
        people_desc = f"成人人数：{adults}，儿童人数：{children}"
        if children and children > 0:
            people_desc += "（有儿童同行：请优先儿童友好景点/餐饮/住宿，控制节奏，注意安全）"
        base_user_message = f"""{city_desc}
出行时间：{start_date} 至 {end_date}
出发地点：{origin if origin else '未填写（默认为目的地城市）'}
{people_desc}
交通: {transportation}
住宿: {accommodation}
偏好: {', '.join(preferences) if preferences else '常规'}

研究数据(景点):
{research_result[:MAX_RESULT_LENGTH] if research_result else '无'}

后勤数据(天气/酒店/餐厅/路线):
{logistics_result[:MAX_RESULT_LENGTH] if logistics_result else '无'}

编排规则：
1. 每天安排 2‑3 个景点，游览时长控制在60‑180分钟
2. 每一天的行程对象**必须携带 city_name 字段，标明该天属于哪一座城市**
3. 多城市场景：不要跨城市安排景点；同一城市的天数集中编排
4. 每一天需要包含早餐、午餐、晚餐安排；结合对应日期天气
5. **启程与返程计入旅行天数**：第1天从出发地启程到目的地，最后一天从目的地返程回出发地
6. **多城市跨城转移**：在不同城市切换时，必须安排跨城交通转移（列车/飞机/高铁），转移时间计入该天行程，不要在不同城市安排景点
7. 输出仅返回完整JSON，禁止多余解释文字、禁止markdown说明。"""

        # ========== 生成行程JSON（主方案 + 两个变体方案） ==========
        # PlanningWorker 为纯 LLM 编排，不需要工具。
        # 优先使用 JSON 模式（OpenAI兼容协议），并放宽 max_tokens，
        # 避免超长行程被截断导致 JSON 损坏；JSON模式失败时回退普通模式。
        # 每个方案都走一次LLM生成：主方案按用户选择类型，其余两个为变体优化。

        async def _generate_plan_json(user_msg: str, usage_holder: dict = None) -> dict:
            """调用LLM生成单个方案JSON，带解析失败自动修复，返回归一化后的plan字典"""
            if usage_holder is None:
                usage_holder = {}
            messages = [
                SystemMessage(content=PLANNING_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ]
            result_text = ""
            try:
                if PLANNING_JSON_MODE:
                    # OpenAI官方模型可开启JSON模式（response_format=json_object），并放宽max_tokens
                    json_llm = llm.bind(response_format={"type": "json_object"}, max_tokens=8192)
                    response = await json_llm.ainvoke(messages)
                else:
                    # 阿里云DashScope qwen3等兼容模型对json_object支持不完善，
                    # 会返回空内容或文档示例JSON，默认关闭JSON模式，靠系统提示词+extract_json提取
                    response = await llm.ainvoke(messages)
                result_text = response.content if hasattr(response, "content") else str(response)
                usage_holder["usage"] = getattr(response, "usage_metadata", None) or {}
            except Exception as e:
                # 内容安全风控：重试会反复触发拦截，直接终止并交由上层兜底
                if is_content_filter_error(str(e)):
                    raise RuntimeError(f"内容安全拦截: {e}") from e
                logger.warning(f"PlanningWorker JSON模式调用失败，回退普通模式: {e}")
                try:
                    response = await llm.ainvoke(messages)
                    result_text = response.content if hasattr(response, "content") else str(response)
                    usage_holder["usage"] = getattr(response, "usage_metadata", None) or {}
                except Exception as e2:
                    # 普通模式同样被风控拦截时，直接终止，避免进入无意义的修复循环
                    if is_content_filter_error(str(e2)):
                        raise RuntimeError(f"内容安全拦截: {e2}") from e2
                    logger.exception("PlanningWorker LLM调用异常")
                    result_text = f"LLM_CALL_ERROR: {str(e2)}"

            # ========== 解析并校验JSON ==========
            try:
                plan = extract_json(result_text)
                if not isinstance(plan, dict):
                    raise ValueError("行程JSON不是对象")
                # 校验必填字段，防止模型输出与行程无关的示例JSON
                _validate_plan_schema(plan)
                # 修复"第0天"bug：强制归一化days的day_index(从0连续递增)与date(逐日补齐)
                normalize_plan_days(plan, start_date=start_date)
                logger.info("PlanningWorker JSON解析成功")
                return plan
            except Exception as e:
                # LLM返回空文本时无需修复（修复也只会拿到空输入），直接判定生成失败
                if not result_text or not result_text.strip():
                    raise RuntimeError(f"LLM返回空文本，无法生成行程JSON: {e}") from e
                # 自动修复一轮：把不合法JSON交给LLM修复，避免直接进Critic重试循环
                logger.warning(f"PlanningWorker JSON解析失败，尝试LLM修复: {e}")
                repair_prompt = (
                    "下面是一段应当为行程JSON的文本，但它不是合法JSON，或缺少必填字段。"
                    "请修复为合法且完整的行程JSON（必须包含 city、start_date、end_date、days 字段），"
                    "只输出修复后的JSON，不要任何解释文字。\n\n"
                    f"{result_text[:6000]}"
                )
                try:
                    repair_response = await llm.ainvoke([
                        SystemMessage(content="你只输出合法JSON，禁止任何多余文字。"),
                        HumanMessage(content=repair_prompt),
                    ])
                    repair_text = repair_response.content if hasattr(repair_response, "content") else str(repair_response)
                    if not repair_text or not repair_text.strip():
                        raise ValueError("修复结果为空白")
                    plan = extract_json(repair_text)
                    if not isinstance(plan, dict):
                        raise ValueError("修复结果不是JSON对象")
                    # 修复结果同样校验必填字段
                    _validate_plan_schema(plan)
                    logger.info("PlanningWorker LLM修复JSON成功")
                except Exception as e2:
                    raise RuntimeError(f"JSON修复失败: {e2}") from e2

                # 修复"第0天"bug：统一走 normalize_plan_days 归一化 days 列表
                normalize_plan_days(plan, start_date=start_date)
                return plan

        # ---- 生成方案（逐代优化：前序方案指标+token用量反馈给后续方案，逐步拉向更优）----
        # 生成顺序固定为 方案一/方案二/方案三，数量由 plan_count 控制；
        # 每个方案串行生成：先算前序方案的真实指标（通勤/花费），再拼成「拉向更优」的反馈
        # 注入给本方案，让后续方案在前序基础上进一步优化；并把每代指标与 LLM token 用量上报 LangFuse。
        ordered_types = list(PLAN_TYPES.keys())[:plan_count]
        plan_variants = []
        prior_records = []   # 记录每个已生成方案的指标与 token 用量，供后续方案反馈
        for variant_type in ordered_types:
            # 基于前序方案构造优化反馈（首个方案无前序时给出通用最优方向）
            prior_feedback = _build_prior_feedback(prior_records, variant_type)
            variant_msg = base_user_message + "\n\n" + prior_feedback
            usage_holder = {}
            try:
                variant_plan = await _generate_plan_json(variant_msg, usage_holder)
            except Exception as e:
                # 方案生成失败：回退为上一个方案（深拷贝），保证方案始终可用且互不共享对象
                logger.warning("PlanningWorker 方案[%s]生成失败，回退前序方案: %s", variant_type, e)
                variant_plan = copy.deepcopy(plan_variants[-1]["plan"]) if plan_variants else None
                if variant_plan is None:
                    logger.warning("PlanningWorker 首个方案生成失败，使用兜底行程: %s", e)
                    variant_plan = _build_fallback_plan(
                        city, city_list, origin, start_date, end_date, travel_days, transportation, accommodation,
                    )
                usage_holder = {}
            # 计算本方案真实指标，作为下一方案的优化靶点，并上报 LangFuse 做对比
            metrics = compute_plan_metrics(variant_plan)
            usage_meta = usage_holder.get("usage") or {}
            prior_records.append({
                "plan_type": variant_type,
                "metrics": metrics,
                "usage": usage_meta,
            })
            _record_variant_langfuse(
                getattr(llm, "model_name", "") or getattr(llm, "model", "") or "unknown",
                variant_type, variant_plan, metrics, usage_meta,
            )
            plan_variants.append({
                "plan_type": variant_type,
                "plan_name": PLAN_TYPES[variant_type]["name"],
                "plan_desc": PLAN_TYPES[variant_type]["desc"],
                "plan": variant_plan,
            })

# 统一贴「方案一/方案二/方案三」标签并附带真实指标（通勤/花费）供前端展示
        plan_variants = relabel_plan_variants(plan_variants)
        # 主方案 planning_result 与用户选择的 plan_type 保持一致
        # （plan_variants 已由逐代循环生成，取其中用户所选类型的方案；为空时回退 None 由上层兜底）
        primary_plan = next(
            (v["plan"] for v in plan_variants if v.get("plan_type") == plan_type),
            plan_variants[0]["plan"] if plan_variants else None,
        )

        # 输出标准化JSON；同时清除旧的审查反馈，让Critic对最新方案重新审查
        return {
            "planning_result": json.dumps(primary_plan, ensure_ascii=False, indent=2),
            "plan_variants": plan_variants,
            "planning_json_broken": False,
            "review_feedback": "",
        }
    return planning_node
