"""LLM 输出中提取合法 JSON 的健壮工具。

大模型输出 JSON 时常伴随 markdown 代码块、前后说明文字、尾随逗号等问题，
本模块提供统一、健壮的提取逻辑，供 PlanningWorker / Critic / API 路由复用。


PlanningWorker ReAct循环输出原始文本
        ↓
extract_json(raw_llm_text) → dict plan
        ↓
normalize_plan_days(plan, start_date)
        ↓
validate_plan_structure(plan)  # Pydantic容错校验
        ↓
relabel_plan_variants 计算通勤、花费指标
        ↓
Critic审查节点

使用自定义extract_json健壮提取 JSON，处理 markdown、括号不匹配、尾随逗号；
normalize_plan_days修复 LLM 幻觉：修正 day_index、补齐日期，重新核算预算保证分项与总和一致；
"""

import json
import re
from datetime import datetime, timedelta


def extract_json(text: str):
    """从 LLM 输出文本中提取并解析 JSON 对象/数组。

    依次尝试：
    1. ```json ... ``` 代码块
    2. ``` ... ``` 普通代码块
    3. 从第一个 { / [ 开始做括号配平截取
    4. 对候选内容去除尾随逗号后再次解析

    Args:
        text: 大模型原始输出文本。

    Returns:
        解析后的 Python 对象（dict / list / 基础类型）。

    Raises:
        ValueError: 文本为空或无法解析出合法 JSON。
    """
    if not text:
        raise ValueError("空文本，无法提取JSON")

    text = text.strip()
    if text.startswith("\ufeff"):
        text = text[1:].strip()

    candidates = []

    # 1. ```json 代码块
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        candidates.append(m.group(1).strip())

    # 2. 普通 ``` 代码块
    m = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())

    # 3. 括号配平截取：第一个 { 或 [ 到匹配的 } / ]
    start = -1
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start >= 0:
        open_ch = text[start]
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end >= 0:
            candidates.append(text[start:end + 1].strip())

    if not candidates:
        raise ValueError("未找到JSON内容")

    errors = []
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            errors.append(str(e))
            # 4. 去除尾随逗号（如 {"a": 1,} 或 [1, 2,]）后重试
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", cand)
                return json.loads(fixed)
            except json.JSONDecodeError:
                continue

    raise ValueError("JSON解析失败: " + "; ".join(errors))

def normalize_plan_days(plan: dict, start_date: str = "") -> dict:
    """归一化行程计划中的 days 列表（原地修改并返回）。

    修复大模型输出的两个典型问题：
    1. day_index 幻觉（全部为0、-1、缺失、乱序）→ 强制从0开始连续递增
    2. date 缺失或与起止日期不一致 → 按 start_date 顺序逐日补齐

    Args:
        plan: 行程计划字典（含 days 列表）。
        start_date: 旅行开始日期 YYYY-MM-DD，用于补齐每日日期。

    Returns:
        归一化后的 plan 字典。
    """
    days = plan.get("days")
    if not isinstance(days, list) or len(days) == 0:
        return plan

    # 解析开始日期；非法时跳过日期补齐，只修复 day_index
    base_date = None
    if start_date:
        try:
            base_date = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            base_date = None
    #序列 解包  i是索引 a[i]=day
    for idx, day in enumerate(days):
        if not isinstance(day, dict):
            continue
        # 强制覆盖大模型幻觉输出的 day_index，从0开始连续递增
        day["day_index"] = idx
        # 日期按开始日期逐日补齐，保证与旅行天数一致
        if base_date is not None:
            day["date"] = (base_date + timedelta(days=idx)).strftime("%Y-%m-%d")

    # 预算强一致性校验与校准，防止 Critic 报错分项之和对不上总预算
    total_attractions = 0
    total_hotels = 0
    total_meals = 0
    total_transportation = 0

    for day in days:
        if not isinstance(day, dict):
            continue
        # 1. 景点门票之和
        for attr in day.get("attractions") or []:
            if isinstance(attr, dict):
                total_attractions += int(attr.get("ticket_price") or 0)
        # 2. 酒店费用之和
        hotel = day.get("hotel")
        if isinstance(hotel, dict):
            total_hotels += int(hotel.get("estimated_cost") or 0)
        # 3. 餐饮之和
        for meal in day.get("meals") or []:
            if isinstance(meal, dict):
                total_meals += int(meal.get("estimated_cost") or 0)
        # 4. 交通费用之和
        t_cost = day.get("transportation_cost") or day.get("transport_cost") or 0
        total_transportation += int(t_cost)

    # 交通如果为0，默认给个兜底值防止显示为空
    if total_transportation == 0:
        total_transportation = 50 * len(days)

    total_budget = total_attractions + total_hotels + total_meals + total_transportation
    plan["budget"] = {
        "total_attractions": total_attractions,
        "total_hotels": total_hotels,
        "total_meals": total_meals,
        "total_transportation": total_transportation,
        "total": total_budget
    }
    return plan
