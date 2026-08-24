"""智能伴游聊天机器人 Agent。

基于 ReAct 循环（默认最多 8 轮迭代），结合行程上下文与工具调用能力，
实现多轮对话交互。
"""

from typing_extensions import AsyncGenerator, List, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from app.agent_graph.config.constant import*

COMPANION_SYSTEM_PROMPT = COMPANION_SYSTEM_PROMPT


class TripCompanionAgent:
    """聊天伴游 Agent，使用 ReAct 循环（最多 8 轮迭代）。"""
    #最大的轮次
    MAX_ITERATIONS = MAX_REACT_ITERATIONS

    def __init__(self, llm: ChatOpenAI, tools: List[BaseTool], plan_json: dict):
        """
                初始化伴游Agent实例
                :param llm: 大模型实例（OpenAI兼容）
                :param tools: 可用工具列表
                :param plan_json: 后端生成的行程计划原始字典数据
                :conversation_history: 历史会话消息
                :plan_context:后端生成的旅行计划
                """
        self.llm = llm
        self.tools = tools
        self.plan_json = plan_json

        # 内存保存对话历史，只在当前Agent实例生命周期有效！⚠️ 重启就丢失，没有持久化到sqlite memory_tools
        self.conversation_history: List[Any] = []
        # 将行程dict转为文本字符串，填入prompt模板
        self.plan_context = self._build_plan_context(plan_json)

        # =========改动=========
        if self.plan_json is not None:
            # 有行程：正常构建行程上下文
            self.plan_context = self._build_plan_context(plan_json)
        else:
            # 无行程场景，固定提示文本
            self.plan_context = "当前没有用户的旅行行程计划。你作为旅行伴游助手，可以回答通用旅行问题、景点、美食、出行建议，不要引用不存在的行程。可以正常调用工具搜索信息。"

        # 构建工具名字 -> 工具对象的映射字典，方便后续根据tool_call名字快速取工具
        self.tool_map = {}
        for t in tools:
            # 取出工具name属性，作为key；value是工具实例
            #对象 属性名 默认是 [""]=对象 字典赋值 key:name Value:对象
            self.tool_map[getattr(t, "name", str(t))] = t

        # 将工具绑定到大模型，llm_with_tools会输出tool_calls结构化字段
        self.llm_with_tools = llm.bind_tools(tools)

    #把dict行程转换成纯文本 str，塞进system prompt给大模型看
    def _build_plan_context(self, plan: dict) -> str:
        """从行程计划构建紧凑的上下文字符串。"""

        # =========改动=========
        if plan is None:
            return "当前没有用户的旅行行程计划。你作为旅行伴游助手，可以回答通用旅行问题、景点、美食、出行建议，不要引用不存在的行程。可以正常调用工具搜索信息。"

        parts = []
        parts.append(f"城市: {plan.get('city', 'N/A')}")
        parts.append(f"日期: {plan.get('start_date', '')} 至 {plan.get('end_date', '')}")
        parts.append("")

        # 遍历每一天行程
        for day in plan.get("days", []):
            day_num = day.get("day_index", 0) + 1
            parts.append(f"第{day_num}天 ({day.get('date', '')}):")
            parts.append(f"  描述: {day.get('description', '')}")

            # 当天景点   默认只取描述的前80个字
            for attr in day.get("attractions", []):
                parts.append(f"  - {attr.get('name', '')}: {attr.get('description', '')[:ATTR_DESCRIPTION_TRUNCATE_LEN ]}")
                parts.append(f"    地址: {attr.get('address', '')}")

            # 当天酒店
            if day.get("hotel"):
                h = day["hotel"]
                parts.append(f"  酒店: {h.get('name', '')} ({h.get('address', '')})")

            parts.append("")
        # 预算信息
        if plan.get("budget"):
            b = plan["budget"]
            parts.append(f"预算: 总计 {b.get('total', 0)} 元")

        parts.append(f"贴士: {plan.get('overall_suggestions', '')}")

        # 列表拼接换行返回完整文本
        return "\n".join(parts)


    async def chat_stream(self, user_message: str) -> AsyncGenerator[str, None]:
        """    通过 ReAct 循环流式回复用户消息。对外暴露的核心API，给后端api路由调用
        Args:
            user_message: 用户的聊天消息。
        Yields:
            回复文本的分块（SSE 流，逐段字符串推送给前端）。
        """
        # 填充system prompt模板，把行程上下文填进去
        system_prompt = COMPANION_SYSTEM_PROMPT.format(plan_context=self.plan_context)

        # 初始化消息列表：最前面放系统提示
        messages = [SystemMessage(content=system_prompt)]

        # 包含最近的对话历史（默认最后 6 条消息）
        if self.conversation_history:
            messages.extend(self.conversation_history[-CONTEXT_WINDOW_RECENT_MSG_COUNT:])

        # 加入本次用户提问
        messages.append(HumanMessage(content=user_message))

        # ReAct 循环，最多 8 轮迭代
        iteration = 0
        full_response = ""

        while iteration < self.MAX_ITERATIONS:
            iteration += 1

            # 这里关键点：使用ainvoke(非流式)拿到结构化tool_calls，不能用astream
            # 因为要先判断有没有调用工具；流式输出的时候tool_call是分块来的不好解析
            response = await self.llm_with_tools.ainvoke(messages)
            messages.append(response)

            # 提取工具调用数组，没有就返回空列表
            tool_calls = getattr(response, "tool_calls", None) or []

            #没有 工具的调用 回复用户
            if not tool_calls:
                # 最终答案：使用已有的回复
                # 通过 astream 重新调用以实现逐 token 输出
                # （messages 已通过 llm_with_tools.ainvoke 包含了 AIMessage）
                response_text = (
                    response.content
                    if hasattr(response, "content") and response.content
                    else str(response)
                )

                full_response = response_text
                # yield把字符串流式吐出，SSE推给前端 单向, webSocket:双向
                yield response_text
                break

            # 执行工具并继续循环
            for tc in tool_calls:
                tool_name = tc.get("name", "unknown")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")

                # 根据名字查找工具实例
                tool = self.tool_map.get(tool_name)
                if tool is None:
                    result = f"错误: 未找到工具 '{tool_name}'"
                #调用工具
                else:
                    try:
                        # 优先异步ainvoke，没有异步实现就走同步invoke
                        if hasattr(tool, "ainvoke"):
                            result = await tool.ainvoke(tool_args)
                        else:
                            result = tool.invoke(tool_args)
                        result = str(result)
                    except Exception as e:
                        # 捕获工具运行异常，把错误信息丢回大模型，不要直接抛崩溃
                        result = f"工具错误: {str(e)}"

                messages.append(
                    ToolMessage(content=str(result), tool_call_id=tool_id)
                )
        else:
            # 达到最大迭代次数：要求 LLM 生成最终答案
            messages.append(
                HumanMessage(
                    content=f"已达到最大 {self.MAX_ITERATIONS} 步限制。请现在给出最终答案。"
                )
            )
            final = await self.llm.ainvoke(messages)
            #防御性容错写法 hasattr:判断返回的AI消息有没有"content"这个属性
            #final.content 消息结果不为空
            final_text = final.content if hasattr(final, "content") and final.content else str(final)
            full_response = final_text
            yield final_text

        # 保存到历史
        self.conversation_history.append(HumanMessage(content=user_message))
        self.conversation_history.append(AIMessage(content=full_response))

        # 裁剪历史 默认保留最新的20
        if len(self.conversation_history) > MAX_HISTORY_TOTAL_LEN:
            self.conversation_history = self.conversation_history[-MAX_HISTORY_TOTAL_LEN:]