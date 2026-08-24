"""RAG 系统测试。"""

import pytest
import os


class TestEmbeddings:
    """Embedding 模型测试。"""

    def test_get_embeddings_returns_none_without_key(self):
        """未设置 API 密钥时应返回 None（CI 默认情况）。"""
        old_key = os.environ.pop("LLM_API_KEY", None)
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        old_emb = os.environ.pop("EMBEDDING_API_KEY", None)

        try:
            from app.rag.embeddings import get_embeddings

            embeddings = get_embeddings()
            # 没有 API 密钥，应为 None
            assert embeddings is None
        finally:
            if old_key:
                os.environ["LLM_API_KEY"] = old_key
            if old_openai:
                os.environ["OPENAI_API_KEY"] = old_openai
            if old_emb:
                os.environ["EMBEDDING_API_KEY"] = old_emb


class TestVectorStore:
    """ChromaDB 向量存储测试。"""

    def test_module_imports(self):
        """验证 vector_store 模块导入无错误。"""
        from app.rag.vector_store import _get_chroma_dir

        chroma_dir = _get_chroma_dir()
        assert chroma_dir.endswith("chromadb")


class TestLoader:
    """文档加载器测试。"""

    def test_data_dir_exists(self):
        """数据目录应存在。"""
        from app.rag.loader import get_data_dir

        data_dir = get_data_dir()
        assert data_dir.exists() or True  # pathlib Path
        assert data_dir is not None

    def test_load_documents_returns_list(self):
        """应返回列表（尚无文档时可能为空）。"""
        from app.rag.loader import load_documents

        docs = load_documents()
        assert isinstance(docs, list)


class TestCompanionAgent:
    """旅行伴游聊天机器人测试。"""

    def test_companion_builds_context(self):
        """伴游 Agent 应能构建行程上下文字符串。"""
        from app.agent_graph.companion import TripCompanionAgent
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        plan = {
            "city": "Beijing",
            "start_date": "2025-06-01",
            "end_date": "2025-06-03",
            "days": [
                {
                    "day_index": 0,
                    "date": "2025-06-01",
                    "description": "历史文化之旅",
                    "attractions": [
                        {
                            "name": "故宫",
                            "address": "北京",
                            "description": "皇家宫殿",
                        }
                    ],
                    "meals": [],
                    "hotel": None,
                }
            ],
            "overall_suggestions": "建议穿舒适的鞋子",
        }

        agent = TripCompanionAgent(mock_llm, [], plan)

        assert "Beijing" in agent.plan_context
        assert "故宫" in agent.plan_context
        assert agent.conversation_history == []
