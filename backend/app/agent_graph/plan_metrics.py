"""行程方案指标计算与方案标签。

- commute_minutes: 行程内通勤总时长（景点间距离按步行速度估算；无坐标时用保守默认值）
- total_cost: 行程总花费（门票 + 酒店 + 餐饮，优先取 plan.budget.total）

方案统一展示为「方案一/方案二/方案三」：按生成顺序编号，不再按指标重贴语义标签；
同时给每个方案附带 plan_metrics，供前端展示「总通勤X分钟 / 总花费¥Y」。


PlanningWorker生成多套plan
    ↓
validate_plan_structure() 做JSON容错校验
    ↓
Critic节点审查
    ↓
relabel_plan_variants(plans)
    └ compute_plan_metrics
        ├ _day_commute_minutes
        │   ├ _get_location
        │   └ _haversine_km
        └ _day_cost
    └ _set_plan_type
    ↓
写入AgentState，返回FastAPI接口，前端读取plan_metrics渲染指标
"""

import logging
import math
from typing_extensions import List, Dict

logger = logging.getLogger(__name__)

# 无坐标信息时的单段通勤默认时长（分钟）：酒店往返与缺失坐标的景点间移动
DEFAULT_TRANSFER_MINUTES: int = 40
# 步行估速（km/h），用于坐标距离换算成移动时间
WALK_SPEED_KMH: float = 4.5


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """哈弗辛公式，计算两点经纬度球面直线距离，单位 km
    不是高德真实路网，会比实际走路距离偏小。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _get_location(attr: dict):
    """从景点字段中提取 (lng, lat)，兼容 location 对象与缺失情况。
    """
    if not isinstance(attr, dict):
        return None
    loc = attr.get("location") or {}
    if isinstance(loc, dict):
        lng = loc.get("longitude") or loc.get("lng")
        lat = loc.get("latitude") or loc.get("lat")
        if lng is not None and lat is not None:
            try:
                return float(lng), float(lat)
            except (TypeError, ValueError):
                return None
    return None


def _day_commute_minutes(day: dict) -> int:
    """估算单日通勤总时长（分钟）：酒店往返 + 景点之间移动。"""
    attrs = day.get("attractions") or []
    if not attrs:
        return 0
    locs = [_get_location(a) for a in attrs]
    total = DEFAULT_TRANSFER_MINUTES  # 酒店 → 第一个景点
    for i in range(len(locs) - 1):
        if locs[i] and locs[i + 1]:
            total += _haversine_km(*(locs[i]), *(locs[i + 1])) / WALK_SPEED_KMH * 60
        else:
            total += DEFAULT_TRANSFER_MINUTES
    total += DEFAULT_TRANSFER_MINUTES  # 最后一个景点 → 酒店
    return int(round(total))


def _day_cost(day: dict) -> int:
    """单日花费：门票 + 酒店 + 餐饮。"""
    total = 0
    for attr in day.get("attractions") or []:
        total += int(attr.get("ticket_price") or 0) if isinstance(attr, dict) else 0
    hotel = day.get("hotel")
    if isinstance(hotel, dict):
        total += int(hotel.get("estimated_cost") or 0)
    for meal in day.get("meals") or []:
        total += int(meal.get("estimated_cost") or 0) if isinstance(meal, dict) else 0
    return total


def compute_plan_metrics(plan: dict) -> dict:
    """计算单个方案的关键指标。"""
    days = plan.get("days") or []
    commute = sum(_day_commute_minutes(d) for d in days if isinstance(d, dict))
    cost = sum(_day_cost(d) for d in days if isinstance(d, dict))
    budget = plan.get("budget")
    if isinstance(budget, dict) and budget.get("total"):
        cost = int(budget.get("total"))
    return {
        "commute_minutes": int(commute),
        "total_cost": int(cost),
        "day_count": len(days),
    }


def _set_plan_type(variant: dict, plan_type: str) -> None:
    """把方案标签与展示名统一为指定类型。"""
    variant["plan_type"] = plan_type
    name_map = {
        "plan_1": ("方案一", "第1套旅行方案（基础完整优化）"),
        "plan_2": ("方案二", "第2套旅行方案（在前序方案基础上进一步优化）"),
        "plan_3": ("方案三", "第3套旅行方案（在前两套基础上继续拉向最优）"),
    }
    name, desc = name_map.get(plan_type, (plan_type, ""))
    variant["plan_name"] = name
    variant["plan_desc"] = desc


def relabel_plan_variants(plans: list) -> list:
    """给方案统一贴「方案一/方案二/方案三」标签，并附带 plan_metrics 供前端展示。

    方案顺序与生成顺序一致（plan_1/plan_2/plan_3），不再按真实指标重排标签；
    每个方案仍会计算总通勤时间与总花费，前端可据此查看各方案差异。
    """
    if not plans:
        return plans
    for p in plans:
        plan = p.get("plan") or {}
        p["plan_metrics"] = compute_plan_metrics(plan)
        ptype = p.get("plan_type") or "plan_1"
        _set_plan_type(p, ptype)
    return plans

