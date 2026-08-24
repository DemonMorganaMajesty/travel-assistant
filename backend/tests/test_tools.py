"""LangChain 工具封装测试。"""

import pytest


def _is_tool(obj):
    """检查对象是否为有效的 LangChain 工具（有 invoke 或可调用）。"""
    return hasattr(obj, "invoke") or hasattr(obj, "name") and hasattr(obj, "args_schema")


class TestAmapTools:
    """高德地图工具定义测试。"""

    def test_amap_text_search_decorator(self):
        """验证 amap_text_search 正确装饰为工具。"""
        from app.tools.amap_tools import amap_text_search
        assert hasattr(amap_text_search, "name")
        assert hasattr(amap_text_search, "invoke")

    def test_amap_weather_decorator(self):
        """验证 amap_weather 正确装饰为工具。"""
        from app.tools.amap_tools import amap_weather
        assert hasattr(amap_weather, "name")
        assert hasattr(amap_weather, "invoke")

    def test_amap_route_decorator(self):
        """验证 amap_route 正确装饰为工具。"""
        from app.tools.amap_tools import amap_route
        assert hasattr(amap_route, "name")
        assert hasattr(amap_route, "invoke")


class TestTavilyTool:
    """Tavily 搜索工具测试。"""

    def test_tavily_search_decorator(self):
        """验证 tavily_search 正确装饰为工具。"""
        from app.tools.tavily_tools import tavily_search
        assert hasattr(tavily_search, "name")
        assert hasattr(tavily_search, "invoke")


class TestFetchTool:
    """网页抓取工具测试。"""

    def test_fetch_webpage_decorator(self):
        """验证 fetch_webpage 正确装饰为工具。"""
        from app.tools.fetch_tools import fetch_webpage
        assert hasattr(fetch_webpage, "name")
        assert hasattr(fetch_webpage, "invoke")


class TestRagTool:
    """RAG 检索工具测试。"""

    def test_rag_lookup_decorator(self):
        """验证 rag_lookup 正确装饰为工具。"""
        from app.tools.rag_tools import rag_lookup
        assert hasattr(rag_lookup, "name")
        assert hasattr(rag_lookup, "invoke")


class TestMemoryTools:
    """SQLite 记忆工具测试。"""

    def test_save_preference_decorator(self):
        """验证 save_user_preference 正确装饰。"""
        from app.tools.memory_tools import save_user_preference
        assert hasattr(save_user_preference, "name")
        assert hasattr(save_user_preference, "invoke")

    def test_get_preference_decorator(self):
        """验证 get_user_preference 正确装饰。"""
        from app.tools.memory_tools import get_user_preference
        assert hasattr(get_user_preference, "name")
        assert hasattr(get_user_preference, "invoke")

    def test_list_preferences_decorator(self):
        """验证 list_user_preferences 正确装饰。"""
        from app.tools.memory_tools import list_user_preferences
        assert hasattr(list_user_preferences, "name")
        assert hasattr(list_user_preferences, "invoke")

    def test_save_and_get_preference(self):
        """测试基本的保存和读取流程。"""
        from app.tools.memory_tools import save_user_preference, get_user_preference

        save_result = save_user_preference.invoke({
            "key": "test_hotel_budget",
            "value": "500",
        })
        assert "test_hotel_budget" in save_result

        get_result = get_user_preference.invoke({"key": "test_hotel_budget"})
        assert "500" in get_result
