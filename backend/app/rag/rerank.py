"""RAG 重排：调用硅流动 BGE-reranker API 对混合检索候选做精排。

职责：在混合检索返回的候选基础上，用 cross-encoder 重排模型按与 query 的相关性重新打分排序，
把最相关片段提到最前；重排失败时回落原顺序，绝不影响主流程。

依赖：httpx（项目已有）；复用 EMBEDDING_API_KEY / EMBEDDING_BASE_URL（与 Embedding 同厂商）。

RAG 链路的后处理精排模块。向量检索召回一批候选文档之后，调用 BGE‑reranker 交叉编码器重排接口，按照和用户
 query 真实相关性重新打分排序；重排异常直接返回原始候选结果，
 保证主业务流程不会崩溃。
"""

import os
import logging
import httpx

from dotenv import load_dotenv
import os
from ..constants import RAG_RERANK_ENABLED


logger = logging.getLogger(__name__)


def _rerank_config():
    """读取重排所需配置：API Key / Base URL，均从 Embedding 配置回退。"""
    api_key = (
        os.getenv("RAG_RERANK_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("EMBEDDING_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = (
        os.getenv("RAG_RERANK_BASE_URL")
        or os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )
    RAG_RERANK_MODEL = os.getenv("RAG_RERANK_MODEL")
    return api_key, base_url, RAG_RERANK_MODEL


async def rerank(query: str, candidates: list, top_n: int = None) -> list:
    """用 BGE-reranker 对候选片段重排。

    Args:
        query: 检索查询文本。
        candidates: 候选列表，每项需含 "content"（文本）与 "source"（来源）。
        top_n: 返回条数上限；为空则返回全部按相关性降序。

    Returns:
        重排后的候选列表（保持原 dict 结构），失败时返回原始顺序。
    """
    # 前置保护：开关关闭 / 无问题 / 无候选 → 直接原路返回，不走网络
    if not RAG_RERANK_ENABLED or not query or not candidates:
        return candidates

    api_key, base_url, RAG_RERANK_MODEL = _rerank_config()
    if not api_key or not base_url or not RAG_RERANK_MODEL:
        logger.info("[rerank] 未配置 API Key/BaseURL，跳过重排")
        return candidates

    url = base_url.rstrip("/") + "/rerank"
    # candidates是向量召回的小候选集合；只提取每个候选的content文本
    #candidates  是向量召回的小列表 不会直接的访问向量库
    documents = [c["content"] for c in candidates]
    payload = {"model": RAG_RERANK_MODEL,
               "query": query, # 用户的问题
               "documents": documents
               }
    if top_n:
        payload["top_n"] = top_n

    try:
        # 异步http请求调用rerank远程API，超时15秒，防止卡死整个Agent
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results") or []
        ordered = []
        #放入ordered
        for item in results:
            idx = item.get("index")
            # 边界校验：防止返回越界的index
            if idx is not None and 0 <= idx < len(candidates):
                ordered.append(candidates[idx])

        # ⭐非常关键的容错逻辑
        # 极端情况：rerank接口只返回部分条目，漏掉几条候选
        # 不能直接用返回的results，否则会丢失文档片段
        seen = set(id(c) for c in ordered)
        # 把没出现在ordered的原始候选全部追加到尾部 防止漏掉
        ordered += [c for c in candidates if id(c) not in seen]

        logger.info(f"[rerank] 重排完成，返回 {len(ordered)} 条")
        return ordered[:top_n] if top_n else ordered
    except Exception as e:
        logger.warning(f"[rerank] 重排失败，回落原顺序: {e}")
        return candidates
