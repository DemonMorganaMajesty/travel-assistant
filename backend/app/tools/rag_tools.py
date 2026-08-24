"""RAG 检索工具，基于 ChromaDB 查询历史文化知识。
LangChain异步Tool，Agent调用，检索景点历史、古迹、民俗知识库片段。
适合历史遗迹、博物馆、传统文化
不用于POI、酒店、餐厅查询。
"""
import json
import logging
from langchain_core.tools import tool
from ..rag.search_cache import cache_lookup, cache_store
from ..rag.hybrid import hybrid_search
from ..rag.rerank import rerank as rerank_candidates
from ..constants import RAG_VECTOR_TOP_N, RAG_RERANK_TOP_N

# 模块日志对象
logger = logging.getLogger(__name__)


@tool
async def rag_lookup(query: str, k: int = 3) -> str:
    """搜索旅行知识库，获取历史文化背景知识。

    适用景点类型：
    - 历史遗迹（故宫、长城、兵马俑）
    - 文化地标（寺庙、博物馆、传统街区）
    - 地方风俗和传统

    不适用：
    - 现代购物中心或娱乐场所
    - 常规酒店/餐厅搜索

    Args:
        query: 关于景点或文化主题的自然语言查询。
        k: 返回的 top 结果数（默认 3）。

    Returns:
        包含相关知识库片段的 JSON 字符串。
    """
    # =========参数校验与边界限制=========
    if not query or not isinstance(query, str):
        err_msg = "参数错误：query查询文本不能为空"
        logger.warning(f"[rag_lookup] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    # 限制k取值范围，防止LLM传入负数或者超大数字
    k = max(1, min(k, 10))
    logger.info(f"[rag_lookup] 执行RAG检索 query={query}, top_k={k}")

    # 检索前先查向量缓存：相同/相似查询直接复用历史检索结果
    cache_query = f"{query} (k={k})"
    cached = cache_lookup("rag", cache_query)
    if cached is not None:
        logger.info(f"[rag_lookup] 命中RAG检索向量缓存 query={query[:60]}")
        return json.dumps(cached, ensure_ascii=False)

    try:
        # 相对导入：延迟导入，仅工具被调用时才加载向量库模块
        from ..rag.vector_store import get_vector_store

        store = get_vector_store()
        if store is None:
            msg = "RAG 知识库不可用。请在 .env 中设置 EMBEDDING_API_KEY 或 OPENAI_API_KEY。"
            logger.warning(f"[rag_lookup] {msg}")
            return json.dumps({"message": msg}, ensure_ascii=False)

        # 混合检索：向量语义 + BM25 关键词两路候选，RRF 融合（比纯向量召回更全）。
        # 候选数取 max(k, RAG_VECTOR_TOP_N)，供下方 rerank 精排后再截断到最终条数。
        snippets = hybrid_search(query, k=max(k, RAG_VECTOR_TOP_N))
        logger.info(f"[rag_lookup] 混合检索完成，融合后候选数量: {len(snippets)}")

        if not snippets:
            msg = "旅行知识库中未找到相关内容。"
            logger.info(f"[rag_lookup] {msg} query={query}")
            return json.dumps({"message": msg}, ensure_ascii=False)

        # BGE-reranker 精排（失败回落原顺序），再截取 top_n 返回下游
        snippets = await rerank_candidates(query, snippets, top_n=RAG_RERANK_TOP_N)
        logger.info(f"[rag_lookup] 重排完成，最终返回 {len(snippets)} 条")

        # 有用检索结果写入向量库，供后续搜索复用
        cache_store("rag", cache_query, {"results": snippets}, {"query": query})
        # 调试保留 indent=2；生产环境删除 indent=2 减少token消耗
        return json.dumps({"results": snippets}, ensure_ascii=False, indent=2)

    except ImportError as e:
        err_msg = f"[rag_lookup] 导入向量库模块失败: {str(e)}，注意该文件不可直接运行，需要作为包导入"
        logger.error(err_msg, exc_info=True)
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except Exception as e:
        err_msg = f"RAG 检索失败: {str(e)}"
        logger.error(f"[rag_lookup] {err_msg}", exc_info=True)
        return json.dumps({"error": err_msg}, ensure_ascii=False)