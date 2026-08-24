"""Critic 节点：对生成的行程计划进行质量审查。
文件定位：LangGraph Agent 图中的 Critic（审查）节点
作用：对 planning 节点输出的旅行计划做校验。
两层校验：
本地 Python 代码做快速结构化校验（不调用大模型，速度快、省钱）
LLM 深度语义审查（逻辑合理性、地理冲突）
超过最大重试次数直接放行，避免无限循环。
输出写回AgentState状态：review_feedback、retry_count、next_worker

planning节点执行完成 → supervisor设置next_worker=critic → 进入critic节点
    critic内部做本地校验(验处理格式、数量字段缺失问题，速度快，不消耗大模型 token。)
    + LLM校验
    critic返回state：
        场景A：校验通过 / 达到最大重试：next_worker=END，review_feedback="pass"
        场景B：校验失败：next_worker=planning/research/logistics，review_feedback="fail:xxx"
↓
执行 graph.py 的 route_after_critic(state)
    if next_worker == END or "pass" in feedback → return END，图结束
    else → return "supervisor"，回到调度器，由supervisor调度对应worker重做
"""

import json
import logging

from langchain_openai.chat_models._client_utils import StreamChunkTimeoutError
from openai import APIConnectionError, APIError
from typing_extensions import Literal, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from .state import AgentState
from langgraph.graph import END
from .json_utils import extract_json

from app.agent_graph.config.constant import (
    MAX_PLAN_RETRY,
    MIN_ATTR_PER_DAY,
    MAX_ATTR_PER_DAY,
    MIN_VISIT_DURATION,
    MAX_VISIT_DURATION,
    REQUIRED_MEAL_TYPES,
    CRITIC_SYSTEM_PROMPT
)

logger = logging.getLogger(__name__)
CRITIC_SYSTEM_PROMPT = CRITIC_SYSTEM_PROMPT


class CriticLLMOutput(BaseModel):
    """Critic大模型输出结构化模型"""
    is_pass: bool
    reason: str
    redo_node: Optional[Literal["research", "logistics", "planning"]]


def create_critic_node(llm: ChatOpenAI):
    parser = PydanticOutputParser(pydantic_object=CriticLLMOutput)
    format_instruction = parser.get_format_instructions()
    full_system_prompt = CRITIC_SYSTEM_PROMPT + "\n" + format_instruction

    async def critic_node(state: AgentState) -> dict:
        planning_result = state.get("planning_result", "")
        retry_count = state.get("retry_count", 0)
        city_list = state.get("city_list")
        travel_days = state.get("travel_days", 0) or 0

        # ✅到达最大重试次数：直接终止图，使用LangGraph标准END
        if retry_count >= MAX_PLAN_RETRY:
            return {
                "next_worker": END,
                "review_feedback": "多次生成校验失败，输出当前可用方案",
                "retry_count": retry_count
            }

        if not planning_result:
            return {
                "review_feedback": "fail: 未生成计划，重新执行规划",
                "retry_count": retry_count + 1,
                "next_worker": "planning",
            }

        try:
            plan = extract_json(planning_result)
            if not isinstance(plan, dict):
                raise ValueError("行程JSON不是对象")
        except (json.JSONDecodeError, ValueError) as e:
            return {
                "review_feedback": f"fail: JSON 结构无效 - {str(e)}",
                "retry_count": retry_count + 1,
                "next_worker": "planning",
            }

        days = plan.get("days", [])
        issues = []
        weather_info_list = plan.get("weather_info", [])
        weather_date_set = {w.get("date") for w in weather_info_list if w.get("date")}

        if len(days) == 0:
            issues.append("计划中没有天数")

        expect_city_day_map = {}
        valid_city_set = set()
        if city_list is not None and len(city_list) > 0:
            for item in city_list:
                c = item["city_name"]
                d = item["stay_days"]
                expect_city_day_map[c] = d
                valid_city_set.add(c)

        actual_city_day_counter = {}
        for i, day in enumerate(days):
            day_no = i + 1
            day_date = day.get("date")
            attrs = day.get("attractions", [])

            if city_list is not None and len(city_list) > 0:
                day_city = day.get("city_name")
                if not day_city:
                    issues.append(f"第{day_no}天行程缺少 city_name 归属城市字段")
                else:
                    if day_city not in valid_city_set:
                        issues.append(f"第{day_no}天 city_name={day_city}，不在本次旅行城市列表{list(valid_city_set)}内")
                    actual_city_day_counter[day_city] = actual_city_day_counter.get(day_city, 0) + 1

            if len(attrs) < MIN_ATTR_PER_DAY:
                issues.append(f"第{day_no}天景点过少（{len(attrs)}个，最少{MIN_ATTR_PER_DAY}个）")
            elif len(attrs) > MAX_ATTR_PER_DAY:
                issues.append(f"第{day_no}天景点过多（{len(attrs)}个，最多{MAX_ATTR_PER_DAY}个）")

            for attr in attrs:
                dur = attr.get("visit_duration", 0)
                if not (MIN_VISIT_DURATION <= dur <= MAX_VISIT_DURATION):
                    attr_name = attr.get("name", "未知景点")
                    issues.append(
                        f"第{day_no}天【{attr_name}】游览时长{dur}分钟，需要{MIN_VISIT_DURATION}-{MAX_VISIT_DURATION}")

            meals = day.get("meals", [])
            meal_types = [m.get("type", "") for m in meals]
            for required in REQUIRED_MEAL_TYPES:
                if required not in meal_types:
                    issues.append(f"第{day_no}天缺少{required}")

            if day_date and day_date not in weather_date_set:
                issues.append(f"第{day_no}天日期{day_date}没有对应的天气信息")

        if city_list is not None and len(city_list) > 0:
            for city_name, expect_days in expect_city_day_map.items():
                real_days = actual_city_day_counter.get(city_name, 0)
                if real_days != expect_days:
                    issues.append(
                        f"城市【{city_name}】期望停留{expect_days}天，实际生成{real_days}天行程，天数不匹配")


        # 单城市模式：行程总天数必须与用户输入 travel_days 一致（多城市模式已在上面按城市逐一校验）
        if (city_list is None or len(city_list) == 0) and travel_days and travel_days > 0 and len(days) != travel_days:
            issues.append(
                f"行程总天数{len(days)}与用户输入的旅行天数{travel_days}不一致")
        if issues:
            return {
                "review_feedback": f"fail: {', '.join(issues)}",
                "retry_count": retry_count + 1,
                "next_worker": "planning",
            }

        # 本地校验通过，调用LLM审查
        messages = [
            SystemMessage(content=full_system_prompt),
            HumanMessage(
                content=(
                    f"请审查以下行程计划：\n\n{json.dumps(plan, ensure_ascii=False, indent=2)}"
                    + f"\n\n用户输入的旅行天数：{travel_days}天"
                    + (
                        "\n\n多城市列表（含每城停留天数）："
                        + str([{ "city_name": it.get("city_name", ""), "stay_days": it.get("stay_days", 0)} for it in city_list])
                        + "。只要 day 的 city_name 在上述列表内即合法，并且各城市实际天数需与 stay_days 一致。"
                        if city_list and len(city_list) > 0 else ""
                    )
                ),
            ),
        ]
        try:
            response = await llm.ainvoke(messages)
            raw_content = response.content.strip()
            logger.debug(f"[Critic] LLM原始输出：{raw_content}")
            llm_out: CriticLLMOutput = parser.parse(raw_content)

        except StreamChunkTimeoutError as e:
            logger.warning(f"[Critic] LLM流块超时 {str(e)}")
            return {
                "review_feedback": f"fail: LLM流生成超时 {str(e)}",
                "retry_count": retry_count + 1,
                "next_worker": "planning",
            }
        except (APIConnectionError, APIError) as e:
            logger.warning(f"[Critic] LLM接口网络异常 {str(e)}")
            return {
                "review_feedback": f"fail: LLM接口异常 {str(e)}",
                "retry_count": retry_count + 1,
                "next_worker": "planning",
            }
        except Exception as e:
            logger.exception(f"[Critic] LLM调用/解析异常 {str(e)}")
            return {
                "review_feedback": f"fail: LLM审查调用异常 {str(e)}",
                "retry_count": retry_count + 1,
                "next_worker": "planning",
            }

        if llm_out.is_pass:
            logger.info("[Critic] LLM审查通过，结束图")
            # ✅校验通过，必须显式返回END终止，不能缺省next_worker
            return {
                "review_feedback": "pass",
                "retry_count": retry_count,
                "next_worker": END
            }
        else:
            feedback_text = f"fail: {llm_out.reason}, 需要重做节点:{llm_out.redo_node}"
            logger.warning(f"[Critic] LLM审查不通过：{feedback_text}")
            return {
                "review_feedback": feedback_text,
                "retry_count": retry_count + 1,
                "next_worker": llm_out.redo_node if llm_out.redo_node else "planning"
            }

    return critic_node
