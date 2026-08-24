"""ResearchWorker：景点搜索 + RAG 检索 + 网页搜索。

专门负责景点信息搜集。调用高德 POI 搜索、RAG 知识库检索、Tavily 网页搜索、网页抓取工具，
搜集 景点 的地址、门票、游览时长、介绍；
输出整理好的景点文本存入research_result，之后交给 LogisticsWorker 做后勤信息搜集。

使用 ReAct（思考-行动-观察）循环，最多 4 轮迭代。

supervisor(next_worker="research") → research_node(llm,tools)
    读取state，组装prompt → run_react_loop 调用高德/Tavily/RAG
    成功/异常降级 → 写回 research_result
→ 固定边回到 supervisor
supervisor读取state["research_result"]，再决定下一步 logistics / planning / critic
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import BaseTool
from typing_extensions import List
from ...agent_graph.state import AgentState
from ...agent_graph.react_loop import run_react_loop
from ..config.constant import RESEARCH_SYSTEM_PROMPT, MAX_REACT_ITERATIONS

import logging

logger = logging.getLogger(__name__)
RESEARCH_SYSTEM_PROMPT = RESEARCH_SYSTEM_PROMPT


def create_research_worker(llm: ChatOpenAI, tools: List[BaseTool]):
    """  最多默认4轮
    创建 ResearchWorker 节点工厂函数
    :param llm: 大模型实例，外部注入，解耦方便单元测试
    :param tools: 工具列表 [amap_text_search, rag_lookup, tavily_search, fetch_webpage]
    :return: research_node 异步节点，供StateGraph add_node注册
    """

    async def research_node(state: AgentState) -> dict:
        """
        LangGraph节点函数：执行景点搜集ReAct循环
        :param state: AgentState 全局状态
        :return: dict 更新AgentState中的research_result字段
        """
        preferences = state.get("preferences", [])
        free_text = state.get("free_text_input", "")
        city = state.get("city", "")
        city_list = state.get("city_list")
        travel_days = state.get("travel_days", 1)
        # 新增：出发地、成人/儿童人数（有儿童时优先搜索儿童友好景点）
        origin = state.get("origin", "") or ""
        adults = state.get("adults", 1) or 1
        children = state.get("children", 0) or 0

        # ========== 多城市/单城市 组装城市描述 ==========
        if city_list is not None and len(city_list) > 0:
            city_parts = []
            for item in city_list:
                c_name = item["city_name"]
                stay_days = item["stay_days"]
                city_parts.append(f"【{c_name}】计划停留 {stay_days} 天")
            city_desc = "本次为多城市旅行：\n" + "\n".join(city_parts)
        else:
            city_desc = f"本次目的地城市：{city}"

        logger.info(f"ResearchWorker 开始搜集景点 {city_desc}, total_days={travel_days}, preferences={preferences}")

        # 参数校验：多城市有city_list就放行；单城市校验city非空
        if (city_list is None or len(city_list) == 0) and not city.strip():
            logger.warning("ResearchWorker：目的地为空，直接终止执行")
            return {
                "research_result": "错误：未填写旅行目的地，无法搜索景点。"
            }

        # 组装送入ReAct的用户提示，携带用户全部业务条件
        children_hint = ""
        if children and children > 0:
            children_hint = f"（有{children}名儿童同行：请额外搜集儿童友好景点，如动物园/科技馆/游乐园/自然公园等，并标注适龄性）"
        user_message = f"""{city_desc}
总旅行天数：{travel_days} 天
出发地点：{origin if origin else '未填写'}
出行人员：成人{adults}人，儿童{children}人{children_hint}

用户偏好: {', '.join(preferences) if preferences else '常规观光'}
额外要求: {free_text if free_text else '无'}

要求：
- 多城市场景，请分别搜集每个城市的景点，**不要混淆不同城市的景点**
- 搜集景点：名称、地址、经纬度、门票价格、开放时间、建议游览时长、简介、评分
- 输出整理清晰的完整景点清单。"""

        # 调用公共ReAct循环，默认最多迭代4次，可并行调用多个搜索工具
        try:
            # 调用ReAct循环 run_react_loop，执行工具调用逻辑，最大迭代4轮
            result_text = await run_react_loop(
                llm=llm,
                tools=tools,
                system_prompt=RESEARCH_SYSTEM_PROMPT,
                user_message=user_message,
                max_iterations=int(MAX_REACT_ITERATIONS/2),
            )
        except Exception as exc:
            logger.exception("ResearchWorker ReAct 未捕获异常，已降级为标准错误结果")
            result_text = f"LLM_FATAL_PROVIDER_ERROR: {str(exc)[:300]}"

        logger.info(f"ResearchWorker 搜集景点完成 {city_desc}")

        return {
            "research_result": result_text,
        }

    return research_node
