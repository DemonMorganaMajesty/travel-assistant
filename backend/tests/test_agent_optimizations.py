"""Agent 工程化新增能力测试：方案指标/重贴标签、路线优化、结构化校验、鉴权、工具容错、用户服务。"""

import asyncio
import json
import pytest


class TestPlanMetrics:
    """方案指标计算与三方案重贴标签测试。"""

    def _make_plan(self, cost: int, far_apart: bool = False) -> dict:
        """构造一个单日行程：费用可调；far_apart 拉大景点距离以增加通勤。"""
        lng_b = 116.60 if far_apart else 116.41
        return {
            "days": [
                {
                    "attractions": [
                        {"name": "A", "ticket_price": cost,
                         "location": {"longitude": 116.40, "latitude": 39.90}},
                        {"name": "B", "ticket_price": 0,
                         "location": {"longitude": lng_b, "latitude": 39.91}},
                    ],
                    "hotel": {"estimated_cost": cost * 2},
                    "meals": [{"estimated_cost": 50}],
                }
            ]
        }

    def test_compute_plan_metrics(self):
        from app.agent_graph.plan_metrics import compute_plan_metrics

        plan = self._make_plan(100)
        m = compute_plan_metrics(plan)
        assert m["day_count"] == 1
        assert m["total_cost"] == 100 + 0 + 200 + 50
        assert m["commute_minutes"] > 0

    def test_relabel_labels_plans_by_type(self):
        from app.agent_graph.plan_metrics import relabel_plan_variants

        # 三个方案按生成顺序编号：plan_1/plan_2/plan_3，展示名为 方案一/方案二/方案三
        plans = [
            {"plan_type": "plan_1", "plan_name": "x", "plan_desc": "", "plan": self._make_plan(500, far_apart=False)},
            {"plan_type": "plan_2", "plan_name": "y", "plan_desc": "", "plan": self._make_plan(100, far_apart=True)},
            {"plan_type": "plan_3", "plan_name": "z", "plan_desc": "", "plan": self._make_plan(900, far_apart=True)},
        ]

        relabeled = relabel_plan_variants(plans)
        assert [p["plan_type"] for p in relabeled] == ["plan_1", "plan_2", "plan_3"]
        assert [p["plan_name"] for p in relabeled] == ["方案一", "方案二", "方案三"]
        # 每个方案都附带真实指标，供前端展示「总通勤X分钟 / 总花费¥Y」
        for p in relabeled:
            assert p["plan_metrics"]["commute_minutes"] > 0
            assert p["plan_metrics"]["total_cost"] > 0
            assert p["plan_metrics"]["day_count"] == 1

    def test_relabel_supports_partial_plan_count(self):
        from app.agent_graph.plan_metrics import relabel_plan_variants

        # 方案数量可调：只生成 1 个或 2 个方案时也要正常贴标签
        one = [{"plan_type": "plan_1", "plan_name": "x", "plan_desc": "", "plan": self._make_plan(200)}]
        relabeled_one = relabel_plan_variants(one)
        assert len(relabeled_one) == 1
        assert relabeled_one[0]["plan_type"] == "plan_1"
        assert relabeled_one[0]["plan_name"] == "方案一"

        two = [
            {"plan_type": "plan_1", "plan_name": "x", "plan_desc": "", "plan": self._make_plan(200)},
            {"plan_type": "plan_2", "plan_name": "y", "plan_desc": "", "plan": self._make_plan(300)},
        ]
        relabeled_two = relabel_plan_variants(two)
        assert [p["plan_type"] for p in relabeled_two] == ["plan_1", "plan_2"]
        assert [p["plan_name"] for p in relabeled_two] == ["方案一", "方案二"]


class TestRouteOptimizer:
    """路线优化工具（OR-Tools 未安装时回退贪心最近邻）测试。"""

    def test_optimize_day_route(self):
        from app.tools.route_optimizer import optimize_day_route

        points = [
            {"name": "A", "longitude": 116.40, "latitude": 39.90},
            {"name": "B", "longitude": 116.41, "latitude": 39.91},
            {"name": "C", "longitude": 116.42, "latitude": 39.92},
        ]
        out = json.loads(optimize_day_route.invoke({"points_json": json.dumps(points, ensure_ascii=False)}))
        assert set(out["order"]) == {"A", "B", "C"}
        assert out["engine"] in ("ortools", "greedy")
        assert out["total_distance_km"] > 0
        assert out["estimated_minutes"] > 0

    def test_optimize_day_route_bad_input(self):
        from app.tools.route_optimizer import optimize_day_route

        out = json.loads(optimize_day_route.invoke({"points_json": '[{"name": "A"}]'}))
        assert "error" in out


class TestPlanSchema:
    """结构化输出 Pydantic 容错校验测试。"""

    def test_rejects_example_json(self):
        from app.agent_graph.plan_schema import validate_plan_structure

        with pytest.raises(ValueError):
            validate_plan_structure({"name": "John", "age": 30, "hobbies": ["reading", "gaming"]})

    def test_accepts_valid_plan(self):
        from app.agent_graph.plan_schema import validate_plan_structure

        valid = {
            "city": "北京",
            "start_date": "2026-08-01",
            "end_date": "2026-08-03",
            "days": [{"date": "2026-08-01", "day_index": 0}],
        }
        assert validate_plan_structure(valid) is valid


class TestAuth:
    """鉴权：bcrypt 密码哈希 + JWT 签发解析。"""

    def test_password_hash_roundtrip(self):
        from app.auth.security import hash_password, verify_password

        h = hash_password("secret123")
        assert verify_password("secret123", h)
        assert not verify_password("wrong-password", h)

    def test_jwt_roundtrip(self):
        from app.auth.jwt_utils import create_access_token, decode_access_token

        token = create_access_token(42, "alice")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "alice"
        assert decode_access_token("bad.token.here") is None


class TestUserService:
    """用户账户服务测试（隔离到临时数据库）。"""

    def test_create_and_query_user(self, tmp_path, monkeypatch):
        from app.services import user_service

        monkeypatch.setattr(user_service, "_DB_PATH", str(tmp_path / "users_test.db"))
        uid = user_service.create_user("tester", "hash-value")
        assert uid is not None

        user = user_service.get_user_by_username("tester")
        assert user["username"] == "tester"
        assert user["password_hash"] == "hash-value"

        # 用户名重复返回 None
        assert user_service.create_user("tester", "another-hash") is None


class TestToolRobustness:
    """ReAct 工具调用健壮性：超时/重试/截断。"""

    def test_retry_on_failure(self):
        from app.agent_graph.react_loop import _invoke_tool_safely

        class FlakyTool:
            name = "flaky"

            def __init__(self):
                self.calls = 0

            async def ainvoke(self, args):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("boom")
                return "ok"

        tool = FlakyTool()
        result = asyncio.run(_invoke_tool_safely(tool, {}))
        assert result == "ok"
        assert tool.calls == 2

    def test_result_truncated(self):
        from app.agent_graph.react_loop import _invoke_tool_safely

        class BigTool:
            name = "big"

            async def ainvoke(self, args):
                return "x" * 10000

        result = asyncio.run(_invoke_tool_safely(BigTool(), {}))
        assert len(result) < 4500
        assert "已截断" in result
