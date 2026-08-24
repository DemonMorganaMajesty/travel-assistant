"""RAG 混合检索：向量语义检索 + BM25 关键词检索，两路经 RRF(Reciprocal Rank Fusion) 融合。

职责：在原有纯向量检索基础上叠加 BM25 关键词召回，同时覆盖「语义近似」与「字面关键词」
两类相似查询，再按排名倒数加权融合，提升召回率。融合逻辑失败时自动降级为纯向量检索，
绝不影响主流程。

依赖：rank_bm25、jieba（中文分词）；两者缺失时自动退回纯向量路。

调用 hybrid_search("鄱阳湖适合玩几天", k=3)
    │
    ├ 如果 RAG_HYBRID_ENABLED=False → 直接调用 _vector_only() 返回纯向量结果
    │
    ├ 通路1：向量检索，取出RAG_VECTOR_TOP_N条候选
    ├ 通路2：_get_bm25()
    │        ├全局缓存不存在 → _get_corpus读取Chroma全部文档 →构建BM25索引存入全局
    │        └存在直接复用内存索引；分词query，BM25打分取RAG_BM25_TOP_N候选
    │
    ├两路候选全部收集；构建fused字典，记录每个文档的vrank（向量排名）brank（BM25排名）
    ├循环计算RRF融合分数 1/(K+rank)
    ├按score降序排序，截取top‑k返回结果
    │
    └任意一路发生异常，该路候选置空，只使用另一路结果；两路全失败返回空列表


"""

import logging
from typing_extensions import List, Optional, Dict

from ..constants import (
    RAG_HYBRID_ENABLED,
    RAG_VECTOR_TOP_N,
    RAG_BM25_TOP_N,
    RAG_HYBRID_FUSE_K,
)

logger = logging.getLogger(__name__)

# 全局 BM25 索引缓存（含全部文档语料）
# 避免每次查询Chroma读取全部文档、重复构建BM25索引，消耗CPU
#知识库新增/删除文档之后，必须调用 reset_bm25_cache()，置为None，下次查询重新构建索引
_bm25_index: Optional[Dict] = None

#鄱阳湖游玩攻略 → jieba 分词得到 ["鄱阳湖","游玩","攻略"]
def _tokenize(text: str) -> List[str]:
    """中文分词：优先 jieba 精确模式，未安装时按空白切分兜底。"""
    try:
        import jieba
        # jieba.lcut 精确分词；过滤空字符串、空白字符
        return [t for t in jieba.lcut(text or "") if t.strip()]
    except Exception:
        ## jieba没有安装、导入报错，兜底直接按空白分割，效果变差但保证不崩溃
        logger.warning("[hybrid] 未安装 jieba，按空白字符切分")
        return [t for t in (text or "").split() if t.strip()]

#_bm25_index是全局内存缓存，程序运行期间一旦构建完成就常驻内存。
#当你往 Chroma 新增、删除、修改知识库文档，内存里面的 BM25 索引还是旧语料。
#必须手动调用本函数，把全局变量置None；下一次执行_get_bm25()会重新从 Chroma拉取全部文档，重建索引。
#如果忘记调用：向量库已经是新文档，BM25 还在用老文档，两路结果不一致，召回错乱。
def reset_bm25_cache() -> None:
    """清空 BM25 索引缓存，知识库重建（build_knowledge_base）后调用。"""
    global _bm25_index
    _bm25_index = None


def _get_corpus() -> List[dict]:
    """从 Chroma 知识库集合拉取全部文档文本与来源，用于构建 BM25 词频-逆文档频率索引。
    如果知识库几万条以上，每次构建 BM25 会慢；本项目是旅行攻略知识库，文档量不大适合这么写。
    """
    try:
        import chromadb
        from .vector_store import _get_chroma_dir

        chroma_dir = _get_chroma_dir()
        client = chromadb.PersistentClient(path=chroma_dir)
        ## 业务知识库集合，travel_knowledge
        col = client.get_or_create_collection(name="travel_knowledge")
        # include=["documents","metadatas"]，取出文档内容和元数据source来源文件名
        data = col.get(include=["documents", "metadatas"])
        docs = []
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        for i, content in enumerate(documents):
            if not content or not content.strip():
                continue
                #防止数组越界
            meta = metadatas[i] if i < len(metadatas) else {}
            docs.append({"content": content, "source": meta.get("source", "unknown")})
        return docs
    except Exception as e:
        logger.warning(f"[hybrid] 读取知识库语料失败，混合检索不可用: {e}")
        return []


def _get_bm25() -> Optional[Dict]:
    """惰性构建并缓存 BM25 索引；未装依赖或无语料时返回 None。"""
    global _bm25_index
    #已经构建过索引，直接返回内存缓存，不重复读取Chroma、不重复训练
    if _bm25_index is not None:
        return _bm25_index

    try:
        from rank_bm25 import BM25Okapi
        #拉取全部知识库文档
        corpus = _get_corpus()
        if not corpus:
            return None
        # 全部文档做中文分词，构建BM25索引
        tokenized = [_tokenize(d["content"]) for d in corpus]
        # 把索引 + 原始语料一起缓存，后续检索需要通过下标拿到原始文档
        bm25 = BM25Okapi(tokenized)
        _bm25_index = {"bm25": bm25, "corpus": corpus}
        logger.info(f"[hybrid] BM25 索引构建完成，语料 {len(corpus)} 条")
        return _bm25_index
    except Exception as e:
        #rank_bm25没有安装 / 语料为空，警告日志，返回None，上层自动降级纯向量
        logger.warning(f"[hybrid] BM25 索引构建失败，降级为纯向量检索: {e}")
        return None


def hybrid_search(query: str, k: int = 3) -> List[dict]:
    """混合检索主入口：向量 + BM25 两路取候选后 RRF 融合。

    Args:
        query: 查询文本。
        k: 融合后返回的候选条数（供下游再精排/截断）。

    Returns:
        融合后的列表，每项 {"content", "source", "score"}，按 RRF 分数降序。
    """
    # 总开关关闭，直接走纯向量检索兜底
    if not RAG_HYBRID_ENABLED or not query:
        return _vector_only(query, k)

    # 1) 向量路候选：相似度最高的 top-N
    vector_cands = []
    try:
        from .vector_store import get_vector_store
        store = get_vector_store()
        if store is not None:
            # similarity_search_with_score 返回 list[(Document,距离分数)]
            # 取 RAG_VECTOR_TOP_N 条，例如取top8候选
            vector_cands = store.similarity_search_with_score(query, k=RAG_VECTOR_TOP_N)
    except Exception as e:
        logger.warning(f"[hybrid] 向量检索失败: {e}")

    # 2) BM25 关键词路候选
    bm25_cands = []
    index = _get_bm25()
    if index:
        try:
            tokens = _tokenize(query)
            # 对全部语料计算BM25匹配分数
            scores = index["bm25"].get_scores(tokens)
            corpus = index["corpus"]
            # 将文档下标按BM25分数从高到低排序，截取前RAG_BM25_TOP_N条候选
            ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:RAG_BM25_TOP_N]
            for i in ranked:
                bm25_cands.append(corpus[i])
        except Exception as e:
            logger.warning(f"[hybrid] BM25 检索失败: {e}")

    # 两路都为空时返回空
    if not vector_cands and not bm25_cands:
        return []

    # 3) RRF 融合：同一文档记录两路排名，score = sum(1/(FUSE_K + rank))
    #优势：不需要两路原始相似度分数，只依赖排序位置，
    # 向量距离分数和 BM25 分数量纲完全不一样，不能直接相加；RRF 完美解决量纲不一致。
    fused: Dict[str, dict] = {}
    # 遍历向量通路候选，记录向量排名 vrank
    for rank, (doc, _score) in enumerate(vector_cands, 1):
        # 用文档全文content做key，同一个文档，两路召回都能命中，会合并到同一个dict
        key = doc.page_content
        item = fused.setdefault(key, {
            "content": key,
            "source": doc.metadata.get("source", "unknown"),
            "vrank": None, "brank": None, "score": 0.0,
        })
        item["vrank"] = rank
    # 遍历BM25通路候选，记录bm25排名 brank
    for rank, item in enumerate(bm25_cands, 1):
        key = item["content"]
        entry = fused.get(key)
        if entry is None:
            entry = fused[key] = {
                "content": key, "source": item["source"],
                "vrank": None, "brank": None, "score": 0.0,
            }
        entry["brank"] = rank
        # 计算RRF总分
    for item in fused.values():
        item["score"] = 0.0
        if item["vrank"]:
            item["score"] += 1.0 / (RAG_HYBRID_FUSE_K + item["vrank"])
        if item["brank"]:
            item["score"] += 1.0 / (RAG_HYBRID_FUSE_K + item["brank"])
    # 根据RRF分数降序，取top‑k返回
    result = sorted(fused.values(), key=lambda e: e["score"], reverse=True)
    return result[:k]


def _vector_only(query: str, k: int) -> List[dict]:
    """纯向量检索兜底（混合检索被关闭或异常时使用）。"""
    try:
        from .vector_store import get_vector_store
        store = get_vector_store()
        if store is None:
            return []
        results = store.similarity_search(query, k=k)
        return [
            {"content": doc.page_content, "source": doc.metadata.get("source", "unknown"), "score": 0.0}
            for doc in results
        ]
    except Exception as e:
        logger.warning(f"[hybrid] 纯向量检索失败: {e}")
        return []
