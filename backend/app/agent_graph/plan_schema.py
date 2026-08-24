"""行程方案结构化校验（Pydantic 容错层）。

用途：把 PlanningWorker 输出的 JSON 做结构化校验与默认值补齐，保证进入下游
（Critic / TripPlan 响应）的数据满足最小结构要求。

设计原则：容错优先——只强制校验影响渲染与下游的关键字段（city/start_date/end_date/days），
景点、餐饮等明细字段缺失时用默认值兜底，避免「校验过严导致整体生成失败」。


PlanningWorker
    → extract_json() 提取json字符串→python dict
    → validate_plan_structure(plan_dict)
        → preprocess_plan_fields(plan)
            → _coerce_str_field()
        → PlanStructure(**plan) 宽松填充默认
        → 手写if强校验city / start_date / end_date / days
    校验成功 → 送入Critic审查节点
    校验失败 → 抛出ValueError，上层捕获，supervisor触发重做planning

Pydantic 容错模型填充的 default 默认值不会回写到外部传入的原始字典，函数依旧返回原始 dict。它仅用来捕获 JSON 嵌套畸形这类解析异常；
业务层面必填字段采用手写 if 做强制校验。如果想要把模型的默认值真正生效，需要接收实例
"""

from typing_extensions import List, Optional
from pydantic import BaseModel, Field, ValidationError


class AttractionLoose(BaseModel):
    """景点明细（容错模型，字段缺省时给默认值）。"""
    name: str = Field(default="")
    address: str = Field(default="")
    location: Optional[dict] = Field(default=None)
    visit_duration: int = Field(default=120)
    description: str = Field(default="")
    category: str = Field(default="景点")
    ticket_price: int = Field(default=0)
    rating: Optional[float] = Field(default=None)
    photos: List[str] = Field(default_factory=list)


class DayLoose(BaseModel):
    """单日行程（容错模型）。"""
    date: str = Field(default="")
    day_index: int = Field(default=0)
    city_name: str = Field(default="")
    description: str = Field(default="")
    transportation: str = Field(default="")
    accommodation: str = Field(default="")
    hotel: Optional[dict] = Field(default=None)
    attractions: List[AttractionLoose] = Field(default_factory=list)
    meals: List[dict] = Field(default_factory=list)


class PlanStructure(BaseModel):
    """行程顶层结构（容错模型）。"""
    city: str = Field(default="")
    city_list: Optional[List[dict]] = Field(default=None)
    origin: str = Field(default="")
    start_date: str = Field(default="")
    end_date: str = Field(default="")
    days: List[DayLoose] = Field(default_factory=list)
    weather_info: List[dict] = Field(default_factory=list)
    overall_suggestions: str = Field(default="")
    budget: Optional[dict] = Field(default=None)


# 原地修改字典，无返回值 先纠正再送给Pydantic
def _coerce_str_field(plan: dict, key: str) -> None:
    """把大模型可能误输出的 list 字段规整为字符串。

    多城市模式下 LLM 常把 city 输出为 ['长春', '大连'] 列表，Pydantic 校验失败会导致
    整个 plan_2/plan_3 生成失败并回退前序方案；统一在这里规整为 长春/大连。
    """
    val = plan.get(key)
    if isinstance(val, list):
        parts = [str(x) for x in val if x is not None and str(x).strip()]
        plan[key] = " / ".join(parts) if parts else ""
    elif val is None:
        plan[key] = ""
    else:
        plan[key] = str(val)

#批量修复 LLM 输出 list 类型的畸形字段。
def preprocess_plan_fields(plan: dict) -> None:
    """校验前规整：所有顶层字符串字段如果被 LLM 输出成 list/None，统一转字符串。"""
    for key in ("city", "origin", "start_date", "end_date", "overall_suggestions"):
        _coerce_str_field(plan, key)

def validate_plan_structure(plan: dict) -> dict:
    """校验并规范化行程字典；缺少必填字段时抛 ValueError。

    Returns:
        原始 plan 字典（保留 LLM 输出的额外字段，仅做校验与类型规整）。
    """
    if not isinstance(plan, dict):
        raise ValueError("行程JSON不是对象")
    try:
        preprocess_plan_fields(plan)
        PlanStructure(**plan)
    except ValidationError as e:
        raise ValueError(f"行程结构校验失败: {e}") from e
    if not plan.get("city"):
        raise ValueError("行程JSON缺少必填字段: city")
    if not plan.get("start_date") or not plan.get("end_date"):
        raise ValueError("行程JSON缺少必填字段: start_date/end_date")
    days = plan.get("days")
    if not isinstance(days, list) or len(days) == 0:
        raise ValueError("行程JSON的days字段为空或不是列表")
    return plan
