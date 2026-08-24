"""搜索结果向量缓存：实现高德POI/天气/路线、Tavily、RAG检索结果的复用。

设计目标：
1. 每次搜索前先查缓存：精确匹配（provider+query 一致）优先，未命中再用向量余弦相似度模糊匹配
2. 命中且未过期直接复用缓存结果，避免重复调用外部API
3. 未命中时把有用结果写入向量库（独立 search_cache 集合），下次搜索直接命中

源搜索向量缓存层。高德 POI / 天气、Tavily 网页搜索、RAG 检索全部走这套缓存。
底层复用同一个 Chroma 磁盘，但是使用独立的 Collection 集合 search_cache
，和旅游知识库travel_knowledge完全隔离。

"""
import json
import logging
import time
from typing_extensions import Optional, Any

from .embeddings import get_embeddings
from .vector_store import _get_chroma_dir
from ..constants import (
    SEARCH_CACHE_ENABLED,
    SEARCH_CACHE_COLLECTION,
    SEARCH_CACHE_COSINE_THRESHOLD,
    SEARCH_CACHE_TTL_HOURS,
    SEARCH_CACHE_DEFAULT_TTL_HOURS,
)

logger = logging.getLogger(__name__)

# 全局缓存 collection 单例（Chroma 原生客户端对象）
_cache_collection = None

#全局单例，拿到独立缓存集合，和旅游知识库分开。
def _get_cache_collection():
    """获取搜索结果缓存用的 Chroma collection（独立于 travel_knowledge 知识库）。

    注意：不绑定 embedding_function，所有读写都显式传入向量，
    避免 langchain 的 OpenAIEmbeddings 与 chroma 原生 EmbeddingFunction 接口不兼容。
    """
    global _cache_collection
    if _cache_collection is None:
        import chromadb

        chroma_dir = _get_chroma_dir()
        client = chromadb.PersistentClient(path=chroma_dir)
        _cache_collection = client.get_or_create_collection(name=SEARCH_CACHE_COLLECTION)
        logger.info(f"[search_cache] 初始化缓存collection={SEARCH_CACHE_COLLECTION}")
    return _cache_collection

#判断缓存是否过期
def _is_fresh(provider: str, meta: dict) -> bool:
    """判断缓存记录是否在有效期内。"""
    ttl_hours = SEARCH_CACHE_TTL_HOURS.get(provider, SEARCH_CACHE_DEFAULT_TTL_HOURS)
    try:
        cached_at = int(meta.get("cached_at", 0) or 0)
    except (TypeError, ValueError):
        return False
    return (time.time() - cached_at) <= ttl_hours * 3600

#原生接口不能直接返回每一条的相似度分数，所以代码自己遍历全部候选，手算余弦相似度。
def _cosine_similarity(vec_a, vec_b) -> float:
    """计算两个向量的余弦相似度。返回值范围[-1,1]，越靠近 1 语义越相似。
向量为空、长度不一致直接返回‑1，代表完全不匹配。
    """
    #向量为空 / 维度不相同 就是不相关 直接返回-;
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return -1.0
    #这是多维向量
    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    norm_a = sum(x * x for x in vec_a) ** 0.5
    norm_b = sum(y * y for y in vec_b) ** 0.5

    #如果模长等于 0（零向量），分母为 0，返回-1防止除零报错。
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


def _to_list(value) -> list:
    """把 Chroma 返回的 numpy 数组/None 统一转为普通 list，
    避免空数组/多元素数组做真值判断时报错。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            return list(value)
    return [value]


def cache_lookup(provider: str, query: str) -> Optional[dict]:
    """查询搜索结果缓存，命中返回缓存的 payload 字典，未命中返回 None。

    流程：先按 provider+query 精确匹配（不调用Embedding，速度快）；
    未命中再对同一 provider 的缓存做向量余弦相似度模糊匹配。
    """
    #总开关关闭，或者查询词为空，直接返回 None，不走缓存逻辑。
    if not SEARCH_CACHE_ENABLED or not query:
        return None
    query = query.strip()

    try:
        #chromaDB 单例对象
        collection = _get_cache_collection()

        # 1) 精确匹配：provider + query 完全一致
        # 注意：chroma 1.5+ 要求多条件用 $and 显式语法，否则报 Expected where to have exactly one operator
        exact = collection.get(
            #provider 完全相等，query 字符串完全相等。
            where={"$and": [{"provider": provider}, {"query": query}]},
            limit=1,
        )
        #_to_list()工具函数：numpy 数组、None 统一转为普通list，统一格式
        docs = _to_list(exact.get("documents"))
        metas = _to_list(exact.get("metadatas"))
        #判断拿到文档不为空；取出这条记录的 metadata 元数据。
        if exact and docs and len(docs) > 0 and docs[0]:
            meta = metas[0] if metas else {}
            #没过期
            if _is_fresh(provider, meta):
                logger.info(f"[search_cache] 精确命中缓存 provider={provider}, query={query[:60]}")
                return json.loads(docs[0])

        # 2) 模糊匹配：向量余弦相似度
        embeddings = get_embeddings()
        if embeddings is None:
            return None
        q_vec = embeddings.embed_query(query)
        cand = collection.get(
            #只拿同一个数据源的缓存，高德的 query 不和 tavily 做相似度匹配！
            where={"provider": provider},
            #返回向量、元数据、存储的 json 文档；默认不会返回向量。
            include=["embeddings", "metadatas", "documents"],
            limit=500,
        )
        best_sim = -1.0
        best_payload = None
        metas = _to_list(cand.get("metadatas"))
        docs = _to_list(cand.get("documents"))
        vecs = _to_list(cand.get("embeddings"))
        for i, meta in enumerate(metas):
            #过期了 继续
            if not _is_fresh(provider, meta):
                continue
            #下标越界保护，防止 vecs 数组长度对不上。
            if i >= len(vecs):
                continue
            #调用手写余弦相似度，计算当前缓存向量和用户 query 向量分数。
            sim = _cosine_similarity(q_vec, vecs[i])
            #如果当前这条相似度大于best_sim，更新最高分，同时保存这条缓存文档内容best_payload。
            if sim > best_sim and docs and i < len(docs):
                best_sim = sim
                best_payload = docs[i]
        #必须同时满足：存在候选记录，相似度大于阈值。阈值是防护：
        # 相似度太低，语义不接近，坚决不复用缓存。
        if best_payload is not None and best_sim >= SEARCH_CACHE_COSINE_THRESHOLD:
            logger.info(f"[search_cache] 向量模糊命中缓存 provider={provider}, query={query[:60]}, sim={best_sim:.3f}")
            return json.loads(best_payload)
    except Exception as e:
        logger.warning(f"[search_cache] 查询缓存异常 provider={provider}: {e}")
    return None


def cache_store(provider: str, query: str, payload: dict, extra_meta: Optional[dict] = None) -> None:
    """把搜索结果写入向量缓存，供后续搜索复用。

    Args:
        provider: 数据源标识，如 amap_poi / amap_weather / amap_route / tavily / rag。
        query: 搜索关键词（作为精确匹配键）。
        payload: 需要缓存的搜索结果（dict，会被序列化为JSON存入向量库）。
        extra_meta: 额外的元数据（如 city、keywords），便于排查。
    """
    if not SEARCH_CACHE_ENABLED or not query:
        return

    query = query.strip()
    try:
        # Embedding未配置时跳过缓存写入，避免阻塞主流程
        embeddings = get_embeddings()
        if embeddings is None:
            return
        collection = _get_cache_collection()
        #son.dumps(payload)：把第三方返回的字典结果序列化为 JSON
        # 字符串存入 document 字段；ensure_ascii=False保证中文不乱码。
        content = json.dumps(payload, ensure_ascii=False)

        # 幂等性重点：同一个 provider+query，可能多次调用 cache_store。
        # 如果不删除旧记录，Chroma 里面会有多条一模一样查询的缓存记录，缓存重复堆积。
        # 先查询，拿到旧记录 id，执行 delete 删除旧数据，再新增一条全新缓存。
        # 注意：chroma 1.5+ 要求多条件用 $and 显式语法
        old = collection.get(
            where={"$and": [{"provider": provider}, {"query": query}]},
            include=[],
        )
        old_ids = _to_list(old.get("ids")) if old else []
        if old_ids:
            #能走到cache_store，说明：要么没有缓存，要么旧缓存已经过期 / 失效，
            #刚刚拿到第三方的新 payload,防止命中过期脏缓存。
            collection.delete(ids=old_ids)

        # 显式计算并传入向量，不依赖collection默认embedding
        vectors = embeddings.embed_documents([content])

        meta: dict = {
            "provider": provider,
            "query": query,
            "cached_at": str(int(time.time())),
            "source": "search_cache",
        }
        if extra_meta:
            meta.update(extra_meta)

        collection.add(
            documents=[content],
            embeddings=vectors,
            metadatas=[meta],
            ids=[f"cache_{provider}_{abs(hash(query))}_{int(time.time() * 1000)}"],
        )
        logger.info(f"[search_cache] 写入缓存成功 provider={provider}, query={query[:60]}")
    except Exception as e:
        logger.warning(f"[search_cache] 写入缓存异常 provider={provider}: {e}")


def clear_cache(provider: Optional[str] = None) -> int:
    """清空搜索结果缓存（可按数据源清空），返回删除条数。"""
    try:
        #传入provider="amap_poi"：只删除高德 POI 这一类缓存
        collection = _get_cache_collection()
        if provider:
            old = collection.get(where={"provider": provider}, include=[])
        else:
            #provider 传 None：删除全部 search_cache 集合的缓存。
            old = collection.get(include=[])

        ids = _to_list(old.get("ids")) if old else []
        if ids:
            collection.delete(ids=ids)
        logger.info(f"[search_cache] 清空缓存完成 provider={provider}, 删除{len(ids)}条")
        return len(ids)
    except Exception as e:
        logger.warning(f"[search_cache] 清空缓存异常 provider={provider}: {e}")
        return 0
