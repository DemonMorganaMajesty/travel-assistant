"""json_utils 工具测试：重点覆盖"第0天"bug 的归一化逻辑。"""

from app.agent_graph.json_utils import extract_json, normalize_plan_days


class TestNormalizePlanDays:
    """days 列表 day_index / date 归一化测试。"""

    def test_fixes_zero_day_index_bug(self):
        """所有天 day_index 都是 0（或 -1）时应被修正为从 0 连续递增。"""
        plan = {
            "days": [
                {"day_index": 0, "date": "2026-08-11"},
                {"day_index": 0, "date": "2026-08-12"},
                {"day_index": -1, "date": "2026-08-13"},
            ]
        }
        normalize_plan_days(plan, start_date="2026-08-11")
        indexes = [day["day_index"] for day in plan["days"]]
        assert indexes == [0, 1, 2]

    def test_dates_filled_from_start_date(self):
        """date 应按 start_date 逐日补齐。"""
        plan = {"days": [{"day_index": 5}, {"day_index": 5}]}
        normalize_plan_days(plan, start_date="2026-08-11")
        dates = [day["date"] for day in plan["days"]]
        assert dates == ["2026-08-11", "2026-08-12"]

    def test_empty_days_unchanged(self):
        """days 为空时不应报错。"""
        plan = {"days": []}
        assert normalize_plan_days(plan, start_date="2026-08-11") == {"days": []}

    def test_invalid_start_date_only_fixes_index(self):
        """开始日期非法时只修复 day_index，不改日期。"""
        plan = {"days": [{"day_index": 0, "date": "2026-08-11"}]}
        normalize_plan_days(plan, start_date="bad-date")
        assert plan["days"][0]["day_index"] == 0
        assert plan["days"][0]["date"] == "2026-08-11"


class TestExtractJson:
    """JSON 提取测试。"""

    def test_extract_from_markdown_block(self):
        text = "```json\n{\"city\": \"北京\"}\n```"
        assert extract_json(text) == {"city": "北京"}

    def test_extract_trailing_comma(self):
        text = '{"city": "北京", "days": [{"a": 1,}]}'
        assert extract_json(text)["city"] == "北京"
