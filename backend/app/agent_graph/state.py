"""Supervisor-Worker-Critic 图的 AgentState 类型定义。"""

from typing_extensions import TypedDict, Annotated, List, Optional, Any
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph 中所有节点共享的状态。

    字段:
        messages: 对话历史（由 add_messages reducer 自动追加）。
        city: 目的地城市。
        city_list: 多城市列表，元素为 {"city_name":"xxx","stay_days":N}；None 代表单城市模式
        start_date: 旅行开始日期 (YYYY‑MM‑DD)。
        end_date: 旅行结束日期 (YYYY‑MM‑DD)。
        travel_days: 旅行天数。
        transportation: 偏好的交通方式。
        accommodation: 住宿偏好。
        preferences: 用户偏好标签列表。
        free_text_input: 额外的自由文本需求。
        origin: 出发地点（返程回到该地点）。
        adults: 成人人数(>=1)。
        children: 儿童人数(>=0)，有儿童时考虑儿童友好路线与景点。
        plan_type: 方案类型 plan_1/plan_2/plan_3，空则默认方案一。
        plan_count: 生成方案数量（1-3），默认3个。
        plan_variants: 方案的完整计划列表（方案一/方案二/方案三）。
        research_result: ResearchWorker 的原始输出。
        logistics_result: LogisticsWorker 的原始输出。
        planning_result: PlanningWorker 的原始输出（最终计划 JSON）。
        next_worker: Supervisor 设置的路由决策。
        review_feedback: Critic 的反馈（计划需要修改时）。
        retry_count: Worker 工具调用/审查整体重试次数。
        worker_retry_count: 单worker内部重试计数（预留）。
        planning_json_broken: planning输出JSON解析损坏标记，True强制进入critic。
    """

    messages: Annotated[List[Any], add_messages]
    city: str
    city_list: Optional[list[dict]]
    start_date: str
    end_date: str
    travel_days: int
    transportation: str
    accommodation: str
    preferences: List[str]
    free_text_input: str
    origin: str
    adults: int
    children: int
    plan_type: str
    plan_count: int

    # 方案完整计划列表（方案一/方案二/方案三），元素结构：
    # {"plan_type": "...", "plan_name": "...", "plan_desc": "...", "plan": {...TripPlan}}
    plan_variants: Optional[list[dict]]

    research_result: Optional[str]
    logistics_result: Optional[str]
    planning_result: Optional[str]

    next_worker: str
    review_feedback: Optional[str]

    retry_count: int
    worker_retry_count: int
    planning_json_broken: bool