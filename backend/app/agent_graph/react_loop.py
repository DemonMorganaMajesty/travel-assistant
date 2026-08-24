"""ReAct（思考-行动-观察）循环实现。
纯底层 ReAct 执行单元。

research worker、logistics worker 都会调用这个函数。
供所有 Worker 节点共用，支持迭代限制和并行工具执行。


run_react_loop()   会有多次React(一次过后 llm 判断还要不要调用工具，如果要则React)
├─ llm_with_tools.ainvoke()          # LLM思考
└─ asyncio.gather()
    └─ _execute_one(tc)              # 内部异步包装函数
        └─ await _invoke_tool_safely(tool, tool_args) # 真正执行工具（超时、重试、截断）
"""

import asyncio
import logging
from typing_extensions import List, Dict, Any, Callable, Optional

from app.agent_graph.config.constant import (
    MAX_REACT_ITERATIONS,
    TOOL_CALL_TIMEOUT_SECONDS,
    TOOL_RETRY_TIMES,
    TOOL_RETRY_BACKOFF_SECONDS,
    MAX_TOOL_RESULT_LENGTH,
)
from app.agent_graph.llm_errors import is_content_filter_error, is_internal_provider_error
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


#：安全执行单个工具，所有外部工具（高德、搜索、网页抓取）统一走这个函数。
async def _invoke_tool_safely(tool: BaseTool, tool_args: dict) -> str:
    """调用单个工具：超时保护 + 失败重试 + 指数退避 + 结果截断。

    - 超时：单次调用超过 TOOL_CALL_TIMEOUT_SECONDS 秒判定失败
    - 重试：异常时最多重试 TOOL_RETRY_TIMES 次，间隔按退避递增
    - 截断：结果超过 MAX_TOOL_RESULT_LENGTH 截断，防止上下文窗口爆炸
    """
    last_err = ""
    for attempt in range(TOOL_RETRY_TIMES + 1):
        try:
            if hasattr(tool, "ainvoke"):
                result = await asyncio.wait_for(
                    tool.ainvoke(tool_args), timeout=TOOL_CALL_TIMEOUT_SECONDS
                )
            else:
                # 没有异步实现：放入线程池调用，避免阻塞事件循环
                result = await asyncio.wait_for(
                    asyncio.to_thread(tool.invoke, tool_args),
                    timeout=TOOL_CALL_TIMEOUT_SECONDS,
                )
            text = str(result)
            if len(text) > MAX_TOOL_RESULT_LENGTH:
                text = text[:MAX_TOOL_RESULT_LENGTH] + f"...[结果已截断，原长度{len(text)}]"
            return text
        except asyncio.TimeoutError:
            last_err = f"工具调用超时(>{TOOL_CALL_TIMEOUT_SECONDS}s)"
        except Exception as e:
            last_err = str(e)
        if attempt < TOOL_RETRY_TIMES:
            await asyncio.sleep(TOOL_RETRY_BACKOFF_SECONDS * (2 ** attempt))
    return f"工具错误: {last_err}"

#当 LLM 一次返回多个工具调用时，通过 asyncio.gather() 并发执行，  非顺序执行。
#React 可以循环多次 每次异步执行所有需要执行的工具
async def run_react_loop(
    llm: ChatOpenAI,
    tools: List[BaseTool],
    system_prompt: str,
    user_message: str,
    max_iterations: int = int(MAX_REACT_ITERATIONS/2),
    #默认这个函数 接受两个str参数 返回值为none 默认是None
    on_tool_call: Optional[Callable[[str, str], None]] = None,
) -> str:
    """执行 ReAct（推理 + 行动）循环，支持并行工具执行。

    当 LLM 一次返回多个工具调用时，通过 asyncio.gather() 并发执行，
    而非顺序执行。

    Args:
        llm: ChatOpenAI 实例。
        tools: 可用的 LangChain 工具列表。
        system_prompt: Agent 的系统消息。
        user_message: 用户的任务描述。
        max_iterations: 最大工具调用迭代次数，超时强制结束。
        on_tool_call: 可选回调(tool_name, status)，用于流式推送进度。

    Returns:
        Agent 的最终回复文本。
    """
    try:
        # 将工具绑定到 LLM：告诉大模型有哪些工具可以调用，开启function‑call
        llm_with_tools = llm.bind_tools(tools)
        # 迭代上限后强制输出文本，杜绝继续调用工具。
        # 注意：不能使用 llm.bind_tools([]) —— 部分OpenAI兼容API会把 tools=[] 原样发给服务端，
        # 直接报 "[] is too short - 'tools'" (400)，导致整个Worker失败；不传tools参数即可禁用工具调用。
        llm_no_tools = llm

        # 构建工具名字→工具实例映射字典，后续拿到llm输出的工具名快速找到对应工具对象
        tool_map: Dict[str, BaseTool] = {}
        for t in tools:
            #对象 属性名 默认值
            name = getattr(t, "name", str(t))
            tool_map[name] = t

        # 开始对话
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]

        iteration = 0
        # ReAct主循环：限制最大迭代，防止无限循环疯狂调用工具
        while iteration < max_iterations:
            iteration += 1

            # 异步请求大模型：思考，决定下一步是输出答案还是调用工具
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            # 提取工具调用列表；没有tool_calls代表模型认为信息足够，可以输出最终结果
            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                # 无工具调用 -> 最终答案
                return response.content if hasattr(response, "content") else str(response)

            # 通过 asyncio.gather 并行执行所有工具调用
            # 拿到单个工具的信息 并且调用第一个函数_invoke_tool_safely 得到结果
            async def _execute_one(tc: dict) -> ToolMessage:
                tool_name = tc.get("name", "unknown")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")

                # 如果传入回调函数，通知上层【该工具开始运行】，用于SSE向前端推送进度
                if on_tool_call:
                    on_tool_call(tool_name, "running")

                # 根据工具名称从map取出工具实例
                tool = tool_map.get(tool_name)
                if tool is None:
                    result = f"错误: 未找到工具 '{tool_name}'"
                else:
                    # 带超时+重试+指数退避+结果截断地调用工具，提升外部API不可靠时的健壮性
                    result = await _invoke_tool_safely(tool, tool_args)
                # 回调通知上层【该工具执行完成】
                if on_tool_call:
                    on_tool_call(tool_name, "done")

                return ToolMessage(content=str(result), tool_call_id=tool_id)

            # asyncio.gather：**并行同时执行全部本次循环的工具调用**，提升速度，不是逐个串行
            tool_results = await asyncio.gather(
                *[_execute_one(tc) for tc in tool_calls]
            )
            # 本轮工具全部返回错误时提前结束循环：
            # 工具持续失败（如高德Key配置/参数错误）时继续迭代只会反复调用LLM，浪费时间和token，
            # 直接进入最终总结，避免用户长时间停留在"正在执行"状态
            if tool_results and all(
                '"error"' in (getattr(r, "content", "") or "").lower()
                for r in tool_results
            ):
                logger.warning("[run_react_loop] 本轮工具调用全部返回错误，提前结束工具循环")
                break
            messages.extend(tool_results)

        # while循环退出：达到最大迭代次数，禁止继续调用工具，强制大模型基于现有全部信息输出结果
        messages.append(
            HumanMessage(
                content="工具调用已达到上限或持续失败。"
                "请基于目前已收集的信息给出最终答案。"
                "不要再调用任何工具。"
            )
        )

        # 这里直接用未绑定工具的llm实例（不带tools参数），彻底禁止模型调用工具
        final_response = await llm_no_tools.ainvoke(messages)
        return final_response.content if hasattr(final_response, "content") else str(final_response)

    except Exception as e:
        # 捕获LLM风控、网络、API全部异常，返回错误字符串写入state，不向上抛出
        # 内容安全风控：重试会反复触发拦截，返回专门标记让supervisor跳过重试
        if is_content_filter_error(str(e)):
            logger.warning("[run_react_loop] 大模型内容安全拦截，跳过重试")
            return f"LLM_CONTENT_FILTER_ERROR: {str(e)[:200]}"
        if is_internal_provider_error(str(e)):
            logger.error("[run_react_loop] 模型服务商内部错误，停止本 Worker 的 ReAct 循环: %s", e)
            return f"LLM_FATAL_PROVIDER_ERROR: {str(e)[:300]}"
        logger.exception("[run_react_loop] ReAct循环发生顶层异常")
        return f"LLM_CALL_ERROR: {str(e)}"
