"""LangGraph Agent 系统的测试。

验证核心图结构和路由逻辑。
"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch
from langgraph.graph import END


def _run(node, state):
    """异步节点测试辅助：同步等待一次节点执行"""
    return asyncio.run(node(state))


class TestAgentState:
    """AgentState TypedDict 测试。"""

    def test_state_fields_exist(self):
        """验证 AgentState 中所有预期字段都已定义。"""
        from app.agent_graph.state import AgentState

        required_fields = [
            "messages", "city", "start_date", "end_date",
            "travel_days", "transportation", "accommodation",
            "preferences", "free_text_input",
            "research_result", "logistics_result", "planning_result",
            "next_worker", "review_feedback", "retry_count",
        ]

        # AgentState 是 TypedDict，检查 __annotations__
        for field in required_fields:
            assert field in AgentState.__annotations__, f"缺少字段: {field}"


class TestSupervisorRouting:
    """Supervisor 路由决策测试。"""

    def test_routes_to_research_when_empty(self):
        """无结果时 Supervisor 应路由到 research（直接路由）。"""
        from app.agent_graph.supervisor import create_supervisor_node
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        node = create_supervisor_node(mock_llm)
        state = {
            "research_result": "",
            "logistics_result": "",
            "planning_result": "",
            "review_feedback": "",
            "retry_count": 0,
        }

        result = _run(node, state)
        assert result["next_worker"] == "research"

    def test_routes_to_finish_when_pass(self):
        """Critic 通过时 Supervisor 应路由到 END（直接路由）。"""
        from app.agent_graph.supervisor import create_supervisor_node
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        node = create_supervisor_node(mock_llm)
        state = {
            "research_result": "done",
            "logistics_result": "done",
            "planning_result": "done",
            "review_feedback": "pass",
            "retry_count": 0,
        }

        result = _run(node, state)
        assert result["next_worker"] == END

    def test_routes_to_end_when_critic_force_passed(self):
        """Critic 重试耗尽强制放行后 Supervisor 必须终止，不得再调度 Worker（防死循环）。"""
        from app.agent_graph.supervisor import create_supervisor_node
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        node = create_supervisor_node(mock_llm)
        state = {
            "research_result": "done",
            "logistics_result": "done",
            "planning_result": "done",
            "review_feedback": "多次生成校验失败，输出当前可用方案",
            "retry_count": 2,
            "planning_json_broken": True,
        }

        result = _run(node, state)
        assert result["next_worker"] == END
        mock_llm.invoke.assert_not_called()

    def test_force_planning_only_when_no_plan(self):
        """重试耗尽时只在尚未生成计划的情况下强制进入 planning，防止 planning->supervisor 死循环。"""
        from app.agent_graph.supervisor import create_supervisor_node
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        node = create_supervisor_node(mock_llm)

        # 已有计划：重试耗尽不应再调度 planning
        r = _run(node, {
            "research_result": "done",
            "logistics_result": "done",
            "planning_result": "done",
            "review_feedback": "fail: 需重做",
            "retry_count": 2,
            "planning_json_broken": False,
        })
        assert r["next_worker"] == END

        # 尚无计划：重试耗尽强制 planning
        r2 = _run(node, {
            "research_result": "",
            "logistics_result": "",
            "planning_result": "",
            "review_feedback": "",
            "retry_count": 2,
            "planning_json_broken": False,
        })
        assert r2["next_worker"] == "planning"

    def test_direct_routing_all_stages(self):
        """测试所有 5 个直接路由阶段均绕过 LLM。"""
        from app.agent_graph.supervisor import create_supervisor_node
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        node = create_supervisor_node(mock_llm)

        # 阶段 1：空 -> research
        r = _run(node, {"research_result":"","logistics_result":"","planning_result":"","review_feedback":"","retry_count":0})
        assert r["next_worker"] == "research"

        # 阶段 2：research 完成 -> logistics
        r = _run(node, {"research_result":"done","logistics_result":"","planning_result":"","review_feedback":"","retry_count":0})
        assert r["next_worker"] == "logistics"

        # 阶段 3：logistics 完成 -> planning
        r = _run(node, {"research_result":"done","logistics_result":"done","planning_result":"","review_feedback":"","retry_count":0})
        assert r["next_worker"] == "planning"

        # 阶段 4：plan 完成 -> critic
        r = _run(node, {"research_result":"done","logistics_result":"done","planning_result":"done","review_feedback":"","retry_count":0})
        assert r["next_worker"] == "critic"

        # 阶段 5：critic 通过 -> END
        r = _run(node, {"research_result":"done","logistics_result":"done","planning_result":"done","review_feedback":"pass","retry_count":0})
        assert r["next_worker"] == END

        # 阶段 6：达到最大重试 -> END
        r = _run(node, {"research_result":"done","logistics_result":"done","planning_result":"done","review_feedback":"fail: bad","retry_count":2})
        assert r["next_worker"] == END

        # LLM 不应被调用（全部为直接路由）
        mock_llm.invoke.assert_not_called()


class TestGraphAssembly:
    """StateGraph 组装测试。"""

    def test_graph_builds_without_errors(self):
        """图应能无运行时错误地编译。"""
        from unittest.mock import MagicMock
        from app.agent_graph.graph import build_trip_planner_graph

        mock_llm = MagicMock()
        tools = [MagicMock()]

        graph = build_trip_planner_graph(mock_llm, tools)

        assert graph is not None
        # 检查所需节点是否存在
        nodes = graph.get_graph().nodes
        node_names = [n for n in nodes]
        assert "supervisor" in node_names
        assert "research" in node_names
        assert "logistics" in node_names
        assert "planning" in node_names
        assert "critic" in node_names


class TestPlanningValidation:
    """PlanningWorker 行程JSON schema 校验测试。"""

    def test_validate_plan_schema_rejects_example_json(self):
        """拒绝模型输出的与行程无关的示例JSON（如 {"name":"John",...}）。"""
        from app.agent_graph.workers.planning import _validate_plan_schema
        import pytest

        with pytest.raises(ValueError):
            _validate_plan_schema({"name": "John", "age": 30, "hobbies": ["reading", "gaming"]})

    def test_validate_plan_schema_accepts_valid_plan(self):
        """合法的行程JSON应通过校验。"""
        from app.agent_graph.workers.planning import _validate_plan_schema

        valid = {
            "city": "北京",
            "start_date": "2026-08-01",
            "end_date": "2026-08-03",
            "days": [{"day_index": 0, "date": "2026-08-01"}],
        }
        _validate_plan_schema(valid)
