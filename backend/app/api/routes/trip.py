"""旅行规划 API 路由，支持 LangGraph + SSE 流式推送。"""

import uuid
import json
#from typing import AsyncGenerator
from collections.abc import AsyncGenerator
from typing_extensions import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from sse_starlette.sse import EventSourceResponse

from ...models.schemas import TripRequest, TripPlanResponse, TripPlan
from ...constants import DEFAULT_PLAN_TYPE, DEFAULT_PLAN_COUNT
from ...agent_graph.state import AgentState
from ...agent_graph.graph import build_trip_planner_graph
from ...agent_graph.companion import TripCompanionAgent
from ...agent_graph.json_utils import extract_json, normalize_plan_days
from ...tools.amap_tools import amap_text_search, amap_weather, amap_route
from ...tools.tavily_tools import tavily_search
from ...tools.fetch_tools import fetch_webpage
from ...tools.rag_tools import rag_lookup
from ...tools.memory_tools import save_user_preference, get_user_preference, load_user_profile, save_user_profile
from ...tools.route_optimizer import optimize_day_route
from ...agent_graph.plan_schema import validate_plan_structure
from ...auth.deps import get_optional_user_id
from ...services import task_service
from ...api.errors import ApiError, CODE_NOT_FOUND

from langchain_openai.chat_models._client_utils import StreamChunkTimeoutError
from openai import APIConnectionError, APIError

import logging

# ----------------------全局日志配置----------------------
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trip", tags=["旅行规划"])

# 模块级缓存：_graph 为编译后的 LangGraph 图（无状态，可被多请求共享，每次调用使用独立 thread_id）
# ⚠️ 注意：伴游Agent改为每次请求独立创建，不再使用全局伴游Agent/全局当前方案，避免多用户互相覆盖
_graph = None
_graph_lock = None
_langfuse_handler = None


def _get_langfuse_handler():
    """创建 LangFuse 回调处理器用于 Agent 追踪。

    自动从环境变量/.env 中读取 LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY、
    LANGFUSE_BASE_URL。未配置时返回 None。
    """
    global _langfuse_handler
    import os

    if _langfuse_handler is None:
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")

        if public_key and secret_key:
            try:
                # v3 必须先初始化顶层Langfuse客户端，自动读取环境变量
                from langfuse import Langfuse
                _ = Langfuse()

                from langfuse.langchain import CallbackHandler
                # v3: CallbackHandler禁止传入pk/sk/host，全部由环境变量提供
                _langfuse_handler = CallbackHandler()

                print(f"LangFuse 追踪已启用 → {host}")
                logger.info(f"LangFuse 追踪已启用 → {host}")
            except ImportError:
                print("LangFuse 未安装, 跳过追踪 (pip install langfuse)")
                logger.info("LangFuse 未安装, 跳过追踪 (pip install langfuse)")
            except Exception as e:
                print(f"LangFuse 初始化失败: {e}")
                logger.error(f"LangFuse 初始化失败: {e}")
        else:
            print("LangFuse 未配置密钥, 跳过追踪 (设置 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY)")
            logger.info("LangFuse 未配置密钥, 跳过追踪 (设置 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY)")

    return _langfuse_handler


def _get_llm():
    """读取环境变量，构造ChatOpenAI兼容大模型实例，支持DeepSeek等兼容OpenAI协议模型"""
    import os
    from langchain_openai import ChatOpenAI
    from ...config import settings  # 触发 .env 加载

    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or settings.openai_api_key
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or settings.openai_base_url
    model = os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL") or settings.openai_model

    if not api_key:
        raise ValueError("LLM_API_KEY 或 OPENAI_API_KEY 未配置")

    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0.3, streaming=True)


def _get_tools():
    """组装Agent全部可用工具列表：高德地图、网页搜索、网页抓取、RAG知识库、用户记忆读写"""
    return [amap_text_search, amap_weather, amap_route, tavily_search, fetch_webpage, rag_lookup,
            optimize_day_route, save_user_preference, get_user_preference]


def _get_graph():
    """单例获取LangGraph实例；只初始化一次，复用graph对象，节省编译开销。

    并发安全说明：LangGraph 编译后的 graph 无共享状态，可被多请求并发调用；
    每次调用使用全新 thread_id（见 _stream_agent_steps），状态互不串扰。
    双检锁（threading.Lock）防止多线程首次同时访问时重复初始化。
    """
    global _graph, _graph_lock
    if _graph is None:
        import threading
        if _graph_lock is None:
            _graph_lock = threading.Lock()
        with _graph_lock:
            if _graph is None:
                _graph = build_trip_planner_graph(_get_llm(), _get_tools())
    return _graph


def _merge_memory_preferences(user_id: Optional[int], prefs: list) -> list:
    """记忆闭环（读取侧）：登录用户未显式填写偏好时，从记忆档案加载历史偏好。"""
    if not user_id or prefs:
        return list(prefs or [])
    profile = load_user_profile(str(user_id))
    saved = profile.get("preferences") if isinstance(profile, dict) else None
    if isinstance(saved, list) and saved:
        logger.info(f"[trip] 已加载用户{user_id}的历史偏好: {saved}")
        return list(saved)
    return list(prefs or [])


def _save_memory_profile(user_id: Optional[int], state: dict, plan_data: dict) -> None:
    """记忆闭环（写入侧）：行程成功后把关键信息写入用户记忆，供下次规划复用。"""
    if not user_id:
        return
    try:
        save_user_profile(str(user_id), {
            "preferences": state.get("preferences") or [],
            "origin": state.get("origin") or "",
            "adults": state.get("adults", 1),
            "children": state.get("children", 0),
            "last_city": plan_data.get("city", ""),
        })
    except Exception as e:
        logger.warning(f"[trip] 保存用户记忆失败: {e}")


async def _exec_plan_task(task_id: str, state: dict, user_id: Optional[int] = None) -> None:
    """后台任务执行器：完整跑一遍 LangGraph 旅行规划图，结果写入任务服务。

    与 SSE 版共用同一套图与结果组装逻辑：进度按节点更新，最终 result 结构与
    SSE 的 result 事件一致，前端轮询到 success 后可直接复用现有渲染逻辑。
    """
    try:
        task_service.update_task(task_id, status=task_service.TASK_RUNNING, progress=5, node="supervisor")
        graph = _get_graph()
        config = {
            "configurable": {"thread_id": f"trip_{uuid.uuid4()}"},
            "recursion_limit": 100,
        }
        lf_handler = _get_langfuse_handler()
        if lf_handler:
            config["callbacks"] = [lf_handler]

        node_progress = {"research": 25, "logistics": 55, "planning": 85, "critic": 95}
        final_values = None
        async for event in graph.astream(state, config, stream_mode="updates"):
            for node_name, node_output in event.items():
                final_values = node_output
                task_service.update_task(
                    task_id,
                    progress=node_progress.get(node_name, 0),
                    node=node_name,
                )
        # updates 模式只返回增量：用 get_state 获取完整快照
        snapshot = graph.get_state(config)
        final_values = snapshot.values if snapshot and snapshot.values else final_values

        if not final_values:
            raise ValueError("Agent 未返回任何结果")

        plan_text = final_values.get("planning_result", "")
        feedback = final_values.get("review_feedback", "")
        plan_data = extract_json(plan_text) if plan_text else None
        if not isinstance(plan_data, dict):
            raise ValueError("行程JSON不是对象")

        # 与 SSE 版一致的结果组装：预测后归一化第0天 bug、注入出发地、组装三方案
        normalize_plan_days(plan_data, start_date=state.get("start_date", ""))
        plan_data.setdefault("origin", state.get("origin", "") or "")
        plan_variants = final_values.get("plan_variants") or []
        plans = []
        if plan_variants:
            for variant in plan_variants:
                v_plan = variant.get("plan") or {}
                if not isinstance(v_plan, dict):
                    continue
                normalize_plan_days(v_plan, start_date=state.get("start_date", ""))
                v_plan.setdefault("origin", state.get("origin", "") or "")
                plans.append({
                    "plan_type": variant.get("plan_type", ""),
                    "plan_name": variant.get("plan_name", ""),
                    "plan_desc": variant.get("plan_desc", ""),
                    "plan": v_plan,
                    "plan_metrics": variant.get("plan_metrics") or {},
                })
        if not plans:
            plans = [{
                "plan_type": DEFAULT_PLAN_TYPE,
                "plan_name": "方案一",
                "plan_desc": "第1套旅行方案",
                "plan": plan_data,
            }]
        # 兜底补齐：确保方案数量与用户选择的 plan_count 一致（失败回退时用首方案深拷贝补齐）
        import copy as _copy
        _req_count = int(state.get("plan_count", 1) or 1)
        while len(plans) < _req_count:
            _src = plans[0]["plan"]
            _clone = _copy.deepcopy(_src)
            _clone["days"] = _copy.deepcopy(_src.get("days") or [])
            _idx = len(plans) + 1
            plans.append({
                "plan_type": f"plan_{_idx}",
                "plan_name": f"方案{'一二三'[_idx - 1] if 1 <= _idx <= 3 else _idx}",
                "plan_desc": f"第{_idx}套旅行方案（自动补齐）",
                "plan": _clone,
                "plan_metrics": {},
            })
        result_data = {
            "plans": plans,
            "active_plan_type": state.get("plan_type", "") or DEFAULT_PLAN_TYPE,
            "request": state,
            "plan": plan_data,
            "review": feedback,
        }
        task_service.update_task(task_id, status=task_service.TASK_SUCCESS, progress=100, node="done", result=result_data)
        # 记忆闭环：行程成功后保存用户偏好档案（登录用户）
        _save_memory_profile(user_id, state, plan_data)
        logger.info(f"[task_service] 任务完成 task_id={task_id}")
    except Exception as e:
        logger.exception(f"[task_service] 任务执行失败 task_id={task_id}: {e}")
        task_service.update_task(task_id, status=task_service.TASK_FAILED, error=str(e))


@router.post("/plan/task", summary="提交行程规划任务（后台异步，前端轮询）")
async def plan_trip_task_submit(
    request: TripRequest,
    idempotency_key: Optional[str] = Header(default=None),
    user_id: Optional[int] = Depends(get_optional_user_id),
):
    """提交行程规划任务，立即返回 task_id；任务在后台执行，前端轮询 /plan/task/{id}。

    幂等：携带相同 idempotency_key 时复用已有任务，避免重复消耗模型与外部接口。
    """
    state = {
        "messages": [],
        "city": request.city,
        "city_list": [item.model_dump() for item in request.city_list] if request.city_list else None,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "travel_days": request.travel_days,
        "transportation": request.transportation,
        "accommodation": request.accommodation,
        "preferences": _merge_memory_preferences(user_id, request.preferences),
        "free_text_input": request.free_text_input or "",
        "origin": request.origin or "",
        "adults": request.adults if request.adults else 1,
        "children": request.children if request.children is not None else 0,
        "plan_type": request.plan_type or "",
        "plan_count": request.plan_count if request.plan_count else DEFAULT_PLAN_COUNT,
        "plan_variants": None,
        "research_result": None,
        "logistics_result": None,
        "planning_result": None,
        "next_worker": "research",
        "review_feedback": None,
        "retry_count": 0,
        "worker_retry_count": 0,
        "planning_json_broken": False,
    }
    task_id, is_new = task_service.create_task(idempotency_key=idempotency_key)
    if not is_new:
        # 幂等命中：直接返回已有任务，不重复提交后台执行
        logger.info(f"[plan/task] 幂等复用 task_id={task_id}")
        return {"task_id": task_id, "reused": True}

    import asyncio
    asyncio.create_task(_exec_plan_task(task_id, state, user_id=user_id))
    return {"task_id": task_id, "reused": False}


@router.get("/plan/task/{task_id}", summary="查询行程规划任务状态")
async def plan_trip_task_status(task_id: str):
    """轮询查询任务状态：pending/running/success/failed；成功时携带 result 数据。"""
    task = task_service.get_task(task_id)
    if task is None:
        raise ApiError(code=CODE_NOT_FOUND, message="任务不存在或已过期", status_code=404)
    return task


async def _stream_agent_steps(state: dict, user_id: Optional[int] = None) -> AsyncGenerator[str, None]:
    """
    SSE流式生成器：以SSE事件流推送Agent每一步执行节点。
    event type: step →节点执行完成；result →最终行程；error →异常。
    :param state: 来自HTTP请求的行程入参
    :yield: json字符串，每一行推送给sse‑starlette
    """
    graph = _get_graph()

    # 组装Agent初始状态，严格对齐AgentState类型定义
    initial_state: AgentState = {
        "messages": [],
        "city": state["city"],
        "city_list": state.get("city_list"),
        "start_date": state["start_date"],
        "end_date": state["end_date"],
        "travel_days": state["travel_days"],
        "transportation": state.get("transportation", "公共交通"),
        "accommodation": state.get("accommodation", "经济型酒店"),
        "preferences": state.get("preferences", []),
        "free_text_input": state.get("free_text_input", ""),
        # 新增：出发地、成人/儿童人数、方案类型
        "origin": state.get("origin", "") or "",
        "adults": state.get("adults", 1) or 1,
        "children": state.get("children", 0) or 0,
        "plan_type": state.get("plan_type", "") or "",
        "plan_count": int(state.get("plan_count", DEFAULT_PLAN_COUNT) or DEFAULT_PLAN_COUNT),
        "plan_variants": None,
        "research_result": None,
        "logistics_result": None,
        "planning_result": None,
        "next_worker": "research",
        "review_feedback": None,
        "retry_count": 0,
        "worker_retry_count": 0,
        "planning_json_broken": False
    }

    node_labels = {
        "supervisor": "正在分析进度...",
        "research": "正在搜索景点...",
        "logistics": "正在规划后勤 (天气/酒店/路线)...",
        "planning": "正在生成行程计划...",
        "critic": "正在审核计划质量...",
    }

    # ✅修复thread_id：每次请求全新uuid，避免多请求互相串状态 + recursion_limit限制最大迭代
    config = {
        "configurable": {"thread_id": f"trip_{uuid.uuid4()}"},
        "recursion_limit": 100
    }
    lf_handler = _get_langfuse_handler()
    if lf_handler:
        config["callbacks"] = [lf_handler]

    final_values = None
    try:
        # stream_mode="updates"：只推送节点输出更新，不推送完整state
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, node_output in event.items():
                label = node_labels.get(node_name, node_name)
                final_values = node_output
                # 发送节点级事件，附带 Worker 结果摘要
                yield json.dumps({
                    "type": "step",
                    "node": node_name,
                    "label": label,
                    "status": "completed",
                    "polling_interval": 2000,
                }, ensure_ascii=False) + "\n"

        # ✅updates模式只返回每个节点的增量更新：planning_result是planning节点早前写入的，
        # 最后一个节点（critic）的增量里不包含它，必须用get_state取完整快照
        snapshot = graph.get_state(config)
        final_values = snapshot.values if snapshot else final_values
        if final_values:
            plan_text = final_values.get("planning_result", "")
            feedback = final_values.get("review_feedback", "")

            try:
                plan_data = extract_json(plan_text)
                if not isinstance(plan_data, dict):
                    raise ValueError("行程JSON不是对象")
                # 兜底归一化：修复"第0天"bug，保证 day_index/date 正确
                normalize_plan_days(plan_data, start_date=state.get("start_date", ""))
                # 注入出发地，供前端结果页展示（LLM可能漏输出该字段）
                plan_data.setdefault("origin", state.get("origin", "") or "")
                # 组装三方案：plan_variants 存在时优先使用，否则单方案兜底
                plan_variants = final_values.get("plan_variants") or []
                plans = []
                if plan_variants:
                    for variant in plan_variants:
                        v_plan = variant.get("plan") or {}
                        if not isinstance(v_plan, dict):
                            continue
                        normalize_plan_days(v_plan, start_date=state.get("start_date", ""))
                        v_plan.setdefault("origin", state.get("origin", "") or "")
                        plans.append({
                            "plan_type": variant.get("plan_type", ""),
                            "plan_name": variant.get("plan_name", ""),
                            "plan_desc": variant.get("plan_desc", ""),
                            "plan": v_plan,
                            "plan_metrics": variant.get("plan_metrics") or {},
                        })
                if not plans:
                    plans = [{
                        "plan_type": DEFAULT_PLAN_TYPE,
                        "plan_name": "方案一",
                        "plan_desc": "第1套旅行方案",
                        "plan": plan_data,
                    }]
                # 兜底补齐：确保方案数量与用户选择的 plan_count 一致
                import copy as _copy
                _req_count = int(state.get("plan_count", 1) or 1)
                while len(plans) < _req_count:
                    _src = plans[0]["plan"]
                    _clone = _copy.deepcopy(_src)
                    _clone["days"] = _copy.deepcopy(_src.get("days") or [])
                    _idx = len(plans) + 1
                    plans.append({
                        "plan_type": f"plan_{_idx}",
                        "plan_name": f"方案{'一二三'[_idx - 1] if 1 <= _idx <= 3 else _idx}",
                        "plan_desc": f"第{_idx}套旅行方案（自动补齐）",
                        "plan": _clone,
                        "plan_metrics": {},
                    })
                # 兼容旧版单方案数据，同时附带多方案列表供前端切换
                result_data = {
                    "plans": plans,
                    "active_plan_type": state.get("plan_type", "") or DEFAULT_PLAN_TYPE,
                    "request": state,
                    "plan": plan_data,
                }
                yield json.dumps({"type": "result", "data": result_data, "review": feedback}, ensure_ascii=False) + "\n"
                # 记忆闭环：行程成功后保存用户偏好档案（登录用户）
                _save_memory_profile(user_id, state, plan_data)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Agent输出JSON解析失败 {e}, raw={plan_text[:200]}")
                yield json.dumps({"type": "result", "data": {"raw": plan_text}, "review": feedback}, ensure_ascii=False) + "\n"

    except StreamChunkTimeoutError as e:
        logger.exception("SSE：大模型流块超时异常")
        yield json.dumps({
            "type": "error",
            "message": f"大模型生成流超时，请重试。详情：{str(e)}"
        }, ensure_ascii=False) + "\n"
    except (APIConnectionError, APIError) as e:
        logger.exception("SSE：LLM接口网络异常")
        yield json.dumps({
            "type": "error",
            "message": f"大模型接口连接失败：{str(e)}"
        }, ensure_ascii=False) + "\n"
    except Exception as e:
        logger.error(f"SSE agent执行异常 {str(e)}", exc_info=True)
        yield json.dumps({
            "type": "error",
            "message": f"行程生成内部错误：{str(e)}"
        }, ensure_ascii=False) + "\n"


@router.post("/plan", summary="生成旅行计划 (SSE 流式)")
async def plan_trip_sse(request: TripRequest, user_id: Optional[int] = Depends(get_optional_user_id)):
    """生成旅行计划，实时 SSE 流式推送 Agent 步骤和工具调用。"""
    state = {
        "city": request.city,
        "city_list": [item.model_dump() for item in request.city_list] if request.city_list else None,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "travel_days": request.travel_days,
        "transportation": request.transportation,
        "accommodation": request.accommodation,
        # 记忆闭环：登录用户未填偏好时自动加载历史偏好
        "preferences": _merge_memory_preferences(user_id, request.preferences),
        "free_text_input": request.free_text_input or "",
        # 新增：出发地、成人/儿童人数、方案类型
        "origin": request.origin or "",
        "adults": request.adults if request.adults else 1,
        "children": request.children if request.children is not None else 0,
        "plan_type": request.plan_type or "",
        "plan_count": request.plan_count if request.plan_count else DEFAULT_PLAN_COUNT,
    }
    return EventSourceResponse(_stream_agent_steps(state, user_id=user_id))


@router.post("/plan/sync", response_model=TripPlanResponse, summary="生成旅行计划 (同步)")
async def plan_trip_sync(request: TripRequest, user_id: Optional[int] = Depends(get_optional_user_id)):
    """"同步生成旅行计划（备用端点，适合调试、后端调用）。"""
    try:
        logger.info(f"收到同步行程规划请求 city={request.city}, multi_city={request.city_list is not None}")
        graph = _get_graph()

        initial_state: AgentState = {
            "messages": [],
            "city": request.city,
            "city_list": [item.model_dump() for item in request.city_list] if request.city_list else None,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "travel_days": request.travel_days,
            "transportation": request.transportation,
            "accommodation": request.accommodation,
            # 记忆闭环：登录用户未填偏好时自动加载历史偏好
            "preferences": _merge_memory_preferences(user_id, request.preferences),
            "free_text_input": request.free_text_input or "",
            # 新增：出发地、成人/儿童人数、方案类型
            "origin": request.origin or "",
            "adults": request.adults if request.adults else 1,
            "children": request.children if request.children is not None else 0,
            "plan_type": request.plan_type or "",
            "plan_count": request.plan_count if request.plan_count else DEFAULT_PLAN_COUNT,
            "plan_variants": None,
            "research_result": None,
            "logistics_result": None,
            "planning_result": None,
            "next_worker": "research",
            "review_feedback": None,
            "worker_retry_count": 0,
            "retry_count": 0,
            "planning_json_broken": False,
        }

        # 同步接口同样使用uuid全新thread_id + recursion_limit=50
        config = {
            "configurable": {"thread_id": f"trip_{uuid.uuid4()}"},
            "recursion_limit": 100
        }
        lf_handler = _get_langfuse_handler()
        if lf_handler:
            config["callbacks"] = [lf_handler]
        # ainvoke：完整执行图，等待全部节点跑完返回最终state
        final_state = await graph.ainvoke(initial_state, config)

        plan_text = final_state.get("planning_result", "")
        try:
            plan_data = extract_json(plan_text)
            if not isinstance(plan_data, dict):
                raise ValueError("行程JSON不是对象")
            # 结构化校验（Pydantic容错层），防止模型输出示例JSON等无效数据
            validate_plan_structure(plan_data)
            # 兜底归一化：修复"第0天"bug，保证 day_index/date 正确
            normalize_plan_days(plan_data, start_date=request.start_date)
            # 注入出发地，供前端结果页展示（LLM可能漏输出该字段）
            plan_data.setdefault("origin", request.origin or "")
            trip_plan = TripPlan(**plan_data)

            # 同步接口同样组装多方案：优先取 planning 节点写入的 plan_variants（数量=用户选择的 plan_count）
            plan_variants = final_state.get("plan_variants") or []
            plans = []
            for variant in plan_variants:
                v_plan = variant.get("plan") or {}
                if not isinstance(v_plan, dict):
                    continue
                normalize_plan_days(v_plan, start_date=request.start_date)
                v_plan.setdefault("origin", request.origin or "")
                validate_plan_structure(v_plan)
                plans.append({
                    "plan_type": variant.get("plan_type", ""),
                    "plan_name": variant.get("plan_name", ""),
                    "plan_desc": variant.get("plan_desc", ""),
                    "plan": v_plan,
                    "plan_metrics": variant.get("plan_metrics") or {},
                })
            if not plans:
                plans = [{
                    "plan_type": DEFAULT_PLAN_TYPE,
                    "plan_name": "方案一",
                    "plan_desc": "第1套旅行方案",
                    "plan": plan_data,
                }]
            # 记忆闭环：行程成功后保存用户偏好档案（登录用户）
            _save_memory_profile(user_id, initial_state, plan_data)
        except Exception as parse_err:
            logger.error(f"同步接口解析行程JSON失败 {parse_err}, raw={plan_text[:300]}", exc_info=True)
            # 不抛500：Critic兜底放行的方案可能不完整，返回成功=false让前端友好提示
            return TripPlanResponse(
                success=False,
                message=f"Agent输出无法解析为合法行程: {parse_err}",
                data=None,
            )

        active_type = initial_state.get("plan_type", "") or DEFAULT_PLAN_TYPE
        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=trip_plan,
            plans=plans,
            active_plan_type=active_type,
        )

    except Exception as e:
        import traceback
        logger.error(f"同步生成行程异常 {str(e)}", exc_info=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.post("/chat", summary="智能伴游对话 (SSE 流式)")
async def chat_companion_stream(request: dict):
    """
    与伴游 Agent 就行程计划进行对话。
    plan可以不传/为null：无行程上下文，仅通用旅行问答
    """
    message = request.get("message", "")
    plan_data = request.get("plan")

    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    logger.info(f"伴游对话请求 message={message[:80]}, plan存在={plan_data is not None}")
    llm = _get_llm()
    tools = _get_tools()

    # 并发安全：伴游Agent每次请求独立创建，不共享全局实例，避免多用户互相覆盖行程上下文
    companion = TripCompanionAgent(llm, tools, plan_data)

    async def chat_stream():
        async for chunk in companion.chat_stream(message):
            yield json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return EventSourceResponse(chat_stream())

@router.get("/health", summary="健康检查")
async def health_check():
    try:
        llm = _get_llm()
        return {"status": "healthy", "service": "trip-travel-assistant-langgraph", "model": llm.model_name}
    except Exception as e:
        logger.error(f"trip健康检查失败 {str(e)}")
        raise HTTPException(status_code=503, detail=f"服务不可用: {str(e)}")
