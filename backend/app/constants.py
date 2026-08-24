"""全局业务常量配置。

把可调参数统一提取到这里集中管理，避免散落在各业务文件里：
搜索缓存（高德/Tavily/RAG）、历史会话记录分页、旅行方案类型等。
"""

# ============ 搜索结果向量缓存（高德 POI/天气/路线、Tavily、RAG） ============
# 是否启用搜索结果向量缓存
SEARCH_CACHE_ENABLED: bool = True
# 缓存集合名称（独立于 travel_knowledge 知识库集合）
SEARCH_CACHE_COLLECTION: str = "search_cache"
# 模糊命中余弦相似度阈值：查询向量与缓存向量余弦相似度 >= 该值视为命中复用
SEARCH_CACHE_COSINE_THRESHOLD: float = 0.85
# 各数据源缓存有效期（小时）：天气变化快，有效期短；知识检索有效期长
SEARCH_CACHE_TTL_HOURS: dict = {
    "amap_poi": 24 * 7,       # 高德POI：7天
    "amap_weather": 24,       # 高德天气：24小时
    "amap_route": 24 * 7,     # 高德路线：7天
    "tavily": 24 * 3,         # Tavily网页搜索：3天
    "rag": 24 * 30,           # RAG知识检索：30天
}
# 未在 TTL 字典中登记的数据源默认有效期
SEARCH_CACHE_DEFAULT_TTL_HOURS: int = 24 * 7

# ============ RAG 检索增强（混合检索 + 重排） ============
# 是否启用混合检索：向量语义检索 + BM25 关键词检索，两路经 RRF 融合（比纯向量召回更全）
RAG_HYBRID_ENABLED: bool = True
# 是否启用 BGE-reranker 重排：对混合检索候选做精排，失败时回落原顺序
RAG_RERANK_ENABLED: bool = True
# 硅流动 BGE 重排模型名（与 Embedding 同厂商，复用 EMBEDDING_API_KEY/BASE_URL）
RAG_RERANK_MODEL: str =""

# 重排后返回给下游的 TopN 片段数
RAG_RERANK_TOP_N: int = 3
# 向量路候选条数（供融合/重排，多于最终返回数，便于召回后精排）
RAG_VECTOR_TOP_N: int = 10
# BM25 关键词路候选条数
RAG_BM25_TOP_N: int = 10
# RRF 融合常数（排名倒数权重参数，越小越强调前排）
RAG_HYBRID_FUSE_K: int = 60


# ============ 历史会话记录 ============
# 历史会话记录每页最大条数
HISTORY_PAGE_SIZE: int = 10
# 历史会话标题最大长度
HISTORY_TITLE_MAX_LEN: int = 60
# 历史会话SQLite数据库文件名（backend/data 目录下）
HISTORY_DB_FILE: str = "trip_history.db"

# ============ 旅行方案类型（最多三个方案） ============
# 方案类型标识 -> 展示名称与说明（前端统一展示为 方案一/方案二/方案三）
PLAN_TYPES: dict = {
    "plan_1": {
        "name": "方案一",
        "desc": "第1套旅行方案（基础完整优化）",
    },
    "plan_2": {
        "name": "方案二",
        "desc": "第2套旅行方案（在前序方案基础上进一步优化）",
    },
    "plan_3": {
        "name": "方案三",
        "desc": "第3套旅行方案（在前两套基础上继续拉向最优）",
    },
}
# 用户不选择方案时的默认方案（第一个方案）
DEFAULT_PLAN_TYPE: str = "plan_1"
# 生成方案数量：默认3个，最少1个，最多3个
DEFAULT_PLAN_COUNT: int = 3
MIN_PLAN_COUNT: int = 1
MAX_PLAN_COUNT: int = 3

# ============ 行程编排（PlanningWorker） ============
# 是否使用 OpenAI 兼容的 response_format={"type":"json_object"} JSON模式生成行程。
# 阿里云DashScope qwen3 等模型对 json_object 支持不完善：会返回空内容或文档示例JSON（如 {"name":"John",...}），
# 默认关闭，改用普通模式+系统提示词约束+extract_json提取；使用 OpenAI 官方模型时可改为 True。
PLANNING_JSON_MODE: bool = False

# ============ 出行人员限制 ============
MIN_ADULTS: int = 1          # 成人数最小值
MIN_CHILDREN: int = 0        # 儿童数最小值
