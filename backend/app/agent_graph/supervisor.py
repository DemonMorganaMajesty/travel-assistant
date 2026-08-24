"""Supervisor：路由决策与直接路由优化。
对已知阶段使用确定性路由，节省 LLM 调用。
仅在复杂决策时调用 LLM（Critic 否决 -> 决定哪个阶段重做）。
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import END
from .state import AgentState
from .llm_errors import is_fatal_external_error
import logging

logger = logging.getLogger(__name__)
MAX_WORKER_RETRY = 2

SUPERVISOR_FAIL_PROMPT = """你是行程规划系统的调度员（Supervisor）。

审查员已否决了计划，反馈如下：
{feedback}

当前重试次数：{retry}/2

哪个 Worker 应该重做？
选项：research, logistics, planning

请只回复一个单词。"""


def is_error_result(text: str) -> bool:
    """判断worker返回结果是否是工具/LLM异常报错文本"""
    if not text:
        return False
    # 注意：工具统一返回 json.dumps({"error": ...})，键是带引号的 "error"，
    # 所以除了裸 "error:" 还要匹配带引号的 '"error"'，否则工具错误永远检测不到
    err_flags = ["LLM_CALL_ERROR:", "[amap_mcp]", "error:", "Error:", '"error"', "error\":"]
    t = text.lower()
    for flag in err_flags:
        if flag.lower() in t:
            return True
    return False


def create_supervisor_node(llm: ChatOpenAI):
    """创建 Supervisor 节点函数，带直接路由优化。

    直接路由（不调用 LLM）用于确定性阶段：
    - init -> research
    - research done, no logistics -> logistics
    - logistics done, no plan -> planning
    - plan done, no feedback -> critic
    - critic pass -> END
    """

    async def supervisor_node(state: AgentState) -> dict:
        logger.info(f"supervisor收到state planning_json_broken={state.get('planning_json_broken')}")

        retry = state.get("retry_count", 0)
        feedback = state.get("review_feedback", "") or ""
        planning_done = bool(state.get("planning_result"))

        # =========终止判定（防止critic/supervisor互相循环触发递归上限）=========
        # Critic已给出结论（pass或重试耗尽强制放行）→ 直接终止，不再调度任何Worker
        if "pass" in feedback.lower() or "多次生成校验失败" in feedback:
            return {"next_worker": END}

        # 优先级最高：planning输出JSON损坏，强制调度critic，不走LLM思考
        if state.get("planning_json_broken", False):
            return {
                "next_worker": "critic"
            }

        # =========保护逻辑：工具多次失败且尚未生成计划，强制进入planning一次=========
        # 注意：必须带 not planning_done 条件，否则planning完成后会反复被调度，造成死循环
        if retry >= MAX_WORKER_RETRY and not planning_done:
            logger.warning(f"supervisor检测工具多次失败 retry_count={retry}，强制进入planning")
            return {"next_worker": "planning"}

        research_result = state.get("research_result", "") or ""
        logistics_result = state.get("logistics_result", "") or ""
        research_has_error = is_error_result(research_result)
        logistics_has_error = is_error_result(logistics_result)

        research_done = bool(research_result)
        logistics_done = bool(logistics_result)

        # --- 直接路由（不调用 LLM）---
        # 阶段1：没有搜索结果 → 执行搜索
        if not research_done:
            return {"next_worker": "research"}

        # research返回报错且未到最大重试：重试research，计数+1
        # 注意：内容风控/高德Key配置错误等致命错误重试无意义，直接跳过重试进入下一阶段
        if research_has_error and retry < MAX_WORKER_RETRY and not is_fatal_external_error(research_result):
            logger.warning(f"supervisor检测research_result存在错误，retry_count {retry} → {retry+1}，重试research")
            return {
                "next_worker": "research",
                "retry_count": retry + 1
            }
        if research_has_error and is_fatal_external_error(research_result):
            logger.warning("supervisor检测research_result为致命错误（内容风控/Key配置），跳过research重试")

        # 阶段2：搜索完成，没有后勤 → 执行后勤
        if not logistics_done:
            return {"next_worker": "logistics"}

        # logistics返回报错且未到最大重试：重试logistics，计数+1
        # 注意：内容风控/高德Key配置错误等致命错误重试无意义，直接跳过重试进入下一阶段
        if logistics_has_error and retry < MAX_WORKER_RETRY and not is_fatal_external_error(logistics_result):
            logger.warning(f"supervisor检测logistics_result存在错误，retry_count {retry} → {retry+1}，重试logistics")
            return {
                "next_worker": "logistics",
                "retry_count": retry + 1
            }
        if logistics_has_error and is_fatal_external_error(logistics_result):
            logger.warning("supervisor检测logistics_result为致命错误（内容风控/Key配置），跳过logistics重试")

        # 阶段3：后勤完成，没有计划 → 执行编排
        if not planning_done:
            return {"next_worker": "planning"}

        # 阶段4：计划完成，尚未审查 → 执行审查
        if not feedback:
            return {"next_worker": "critic"}

        # 阶段5：审查失败且重试次数耗尽 → 强制结束（避免无限循环）
        if retry >= MAX_WORKER_RETRY:
            return {"next_worker": END}

        # --- 复杂决策：LLM 路由处理失败情况 ---
        # 当Critic审查节点否决行程方案之后，进入该分支：让LLM判断应该交给哪个worker重新执行
        # 传入审查反馈feedback，以及当前已经重试的次数retry
        prompt = SUPERVISOR_FAIL_PROMPT.format(feedback=feedback, retry=retry)
        # 组装给大模型的消息：系统提示词 + 人类提问
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="哪个 Worker 应该重做？"),
        ]

        try:
            # 异步调用LLM，让它输出需要重做的worker名称
            response = await llm.ainvoke(messages)
            # 拿到返回内容，去除首尾空格、转小写，统一格式
            decision = response.content.strip().lower()
            logger.debug(f"[Supervisor] LLM原始输出决策: |{decision}|")
        except Exception as e:
            # LLM调用异常：网络超时、限流、接口报错等，做降级兜底，默认走planning重新编排行程
            logger.exception("[Supervisor] LLM路由调用发生异常，兜底选择planning")
            decision = "planning"

        # 合法worker集合，只允许这三个任务节点
        valid = ["research", "logistics", "planning"]
        if decision not in valid:
            """
               兜底逻辑1：大模型输出乱码/多余文字，没有返回合法worker名字
               尝试从critic的否决反馈文本里面，关键词匹配，猜测该跑哪个worker
               """
            fb_lower = feedback.lower()
            for w in valid:
                if w in fb_lower:
                    decision = w
                    break
            else:
                decision = "planning"

        # 返回更新后的AgentState状态，交给LangGraph流转
        return {
            "next_worker": decision,
            "review_feedback": "",
            "retry_count": retry + 1,
        }

    return supervisor_node
