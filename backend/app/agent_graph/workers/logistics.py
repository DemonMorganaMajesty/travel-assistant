"""LogisticsWorker：天气、酒店、路线、美食推荐。

使用 ReAct（思考-行动-观察）循环，最多 4 轮迭代。

属于 Worker 节点，LangGraph 的其中一个业务节点。
作用：搜集天气、酒店、本地路线、美食、出发‑到达‑返程跨城交通；输出写入logistics_result。
和 ResearchWorker 结构完全对称，复用公共run_react_loop，最多 4 轮 ReAct 迭代；
执行完依靠固定边直接回到supervisor，本节点不做任何调度决策，不修改 retry_count、不设置 next_worker。

supervisor(next_worker="logistics") → logistics_node
    读取state，带上research_result上下文 → run_react_loop调用高德工具
    成功/异常降级 → 写回 logistics_result
→ 固定边回到 supervisor
supervisor读取 logistics_result，决定下一步 planning / critic / 重试 logistics
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import BaseTool
from typing_extensions import List

from ..config.constant import MAX_REACT_ITERATIONS,LOGISTICS_SYSTEM_PROMPT,MAX_RESULT_LENGTH
from ...agent_graph.state import AgentState
from ...agent_graph.react_loop import run_react_loop
import logging

logger = logging.getLogger(__name__)
LOGISTICS_SYSTEM_PROMPT = LOGISTICS_SYSTEM_PROMPT


def create_logistics_worker(llm: ChatOpenAI, tools: List[BaseTool]):
    """   默认最多4轮
       创建 LogisticsWorker 节点工厂函数
       :param llm: 全局共享大模型实例，外部注入，方便单元测试mock
       :param tools: 工具列表，传入高德天气、搜索、路线工具
       :return: logistics_node 异步节点函数，供StateGraph add_node注册使用
       """
    async def logistics_node(state: AgentState) -> dict:
        """
        LangGraph 真正执行的节点函数
        入参 state：AgentState，整个图的全局状态字典
        返回 dict：需要更新写入AgentState的字段
        """
        city = state.get("city", "")
        city_list = state.get("city_list")
        start_date = state.get("start_date", "")
        end_date = state.get("end_date", "")
        accommodation = state.get("accommodation", "经济型酒店")
        transportation = state.get("transportation", "公共交通")
        research_result = state.get("research_result", "")
        # 新增：出发地、成人/儿童人数（有儿童时考虑家庭友好后勤）
        origin = state.get("origin", "") or ""
        adults = state.get("adults", 1) or 1
        children = state.get("children", 0) or 0

        # =========组装城市描述 多城市/单城市=========
        if city_list is not None and len(city_list) > 0:
            city_parts = []
            for item in city_list:
                c_name = item["city_name"]
                stay_days = item["stay_days"]
                city_parts.append(f"【{c_name}】计划停留 {stay_days} 天")
            city_desc = "本次为多城市旅行：\n" + "\n".join(city_parts)
        else:
            city_desc = f"目的地城市：{city}"

        logger.info(f"LogisticsWorker 开始执行, {city_desc}, date:{start_date}~{end_date}")

        # 参数校验：多城市存在city_list就放行；单城市校验city非空
        if (city_list is None or len(city_list) == 0) and not city.strip():
            logger.warning("LogisticsWorker：目的地城市为空，直接终止执行")
            return {"logistics_result": "错误：缺少旅行目的地城市信息，无法搜集后勤信息。"}

        children_hint = ""
        if children and children > 0:
            children_hint = f"（有{children}名儿童同行：酒店优先家庭房/儿童友好，路线选择步行少、换乘少的轻松方案，餐厅适合家庭用餐）"
        user_message = f"""{city_desc}
出行时间范围：{start_date} 至 {end_date}
出发地点：{origin if origin else '未填写'}
出行人员：成人{adults}人，儿童{children}人{children_hint}

住宿偏好: {accommodation}
交通方式: {transportation}

已搜集景点信息:
{research_result[:MAX_RESULT_LENGTH] if research_result else '暂无搜索结果。'}

请按要求完成后勤信息搜集：
1. 获取整个出行时间段内**所有城市**的天气预报
2. 分别为每个城市搜索景点聚集区附近的酒店推荐
3. 规划同一城市内部景点之间的路线，不要跨城市乱规划路线
4. 搜索各个城市景点周边餐厅、美食推荐
5. 额外规划从出发地到目的地、以及从目的地返回出发地的跨城路线（返程计入旅行天数）

⚠️多城市场景注意：每个城市的天气、酒店、餐厅分开整理，禁止把A城市后勤信息归到B城市。"""

        # 调用公共ReAct循环，执行工具调用逻辑，最大迭代4轮
        try:
            result_text = await run_react_loop(
                llm=llm,
                tools=tools,
                system_prompt=LOGISTICS_SYSTEM_PROMPT,
                user_message=user_message,
                max_iterations=int(MAX_REACT_ITERATIONS/2),
            )
        except Exception as exc:
            logger.exception("LogisticsWorker ReAct 未捕获异常，已降级为标准错误结果")
            result_text = f"LLM_FATAL_PROVIDER_ERROR: {str(exc)[:300]}"
        logger.info("LogisticsWorker 执行完成，已获取后勤搜集结果")
        # LangGraph节点返回字典，key=value，会自动合并更新到AgentState
        return {
            "logistics_result": result_text,
        }

    # 返回内部异步节点函数，交给graph注册
    return logistics_node
