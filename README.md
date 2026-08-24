```
# Smart Travel Planner - LangGraph Multi‑Agent System
基于 **LangChain + LangGraph** 的多 Agent 智能旅行规划后端系统，采用 Supervisor‑Worker‑Critic 架构，实现多城市多套旅行方案生成、预算计算、行程质量校验，支持会话历史持久化、地图展示、未登录匿名降级访问。

## 架构亮点
### Supervisor‑Worker‑Critic 多 Agent 协作
```

Supervisor (总调度路由决策)
-> ResearchWorker  (景点检索 + RAG 知识库 + Tavily 网页搜索)
-> LogisticsWorker (天气 + 酒店 + 路线 + 美食后勤信息搜集)
-> PlanningWorker  (预算核算 + 多版本每日行程编排)
-> Critic           (双层质量审查：结构化校验 + LLM 语义校验)
-> pass -> 输出最终行程方案 /fail -> 回退 Supervisor 重新调度重试

```
> 内置最大重试计数、ReAct迭代上限、强制终止条件，规避LangGraph图节点之间无限循环死锁问题。

### 核心技术栈
| 技术 | 用途 | 业务驱动 |
|------|------|---------|
| LangGraph | 多 Agent 工作流编排 | Supervisor‑Worker‑Critic 状态图调度 |
| LangChain | LLM、工具调用封装 | `@tool` 统一工具接口、Prompt管理 |
| ChromaDB | RAG向量库 + 搜索结果向量缓存 | 旅行攻略知识库、复用第三方检索结果 |
| SQLite | 会话历史持久化 | 保存用户行程历史，支持会话新建/删除/置顶 |
| FastAPI | Web后端服务 | 接口服务、异步后台任务、可选鉴权 |
| RRF + BM25 + BGE‑Reranker | RAG混合检索精排 | 向量+关键词多路召回融合、结果重排序 |
| httpx | 第三方HTTP客户端 | 高德地图API同步/异步封装，替换MCP子进程方案 |

### 工具矩阵
| 工具 | 业务场景 |
|------|---------|
| AmapService(httpx) | POI搜索、地理编码、路线规划、天气查询 |
| Tavily Search | 获取景点门票、开放时间、最新旅行攻略 |
| Fetch | 网页攻略文本抓取 |
| RAG(ChromaDB+BM25+BGE) | 旅行知识库检索，补充景点背景知识 |
| 向量缓存集合 | 缓存高德、Tavily、RAG检索结果，降低第三方调用频次 |

### 可靠性设计
1. **Worker内部封装手写ReAct循环**：控制工具最大迭代轮次，支持超时、指数退避+随机抖动重试、工具返回结果截断；区分致命错误（密钥错误、内容风控），跳过无效重试。
2. **健壮JSON解析**：处理LLM输出Markdown代码块、残缺JSON，通过括号深度配平提取目标结构，配合Pydantic做结构化校验。
3. **混合检索自动降级**：BM25/BGE依赖缺失时自动回退纯向量检索，保证主流程不中断。
4. **向量缓存策略**：精确匹配 + 余弦相似度模糊匹配 + 分类TTL；复用高德POI、天气、路线、Tavily检索结果。

## 项目结构
```

backend/
app/
agent_graph/          # LangGraph Agent 核心模块
state.py            # AgentState TypedDict 全局状态定义
supervisor.py       # Supervisor 调度路由节点
workers/            # Research / Logistics / Planning Worker 实现，内置 run_react_loop
critic.py           # Critic 双层校验审查节点
graph.py            # StateGraph 构建与编译
tools/                # 工具层
amap_tools.py       # 高德 API httpx 封装（替换原 MCP 子进程）
tavily_tools.py     # Tavily 网页搜索工具
fetch_tools.py      # 网页内容抓取
rag_tools.py        # RAG 检索入口
cache_tools.py      # 向量缓存逻辑
rag/                  # RAG 系统
vector_store.py     # ChromaDB 实例管理（知识库 + 缓存两套集合）
embeddings.py       # Embedding 模型封装
loader.py           # 文档加载、文本分块
data/               # 原始攻略知识库文档
api/                  # FastAPI 路由接口
models/               # Pydantic 数据模型定义
db/                   # SQLite 会话历史存储
tests/                  # 单元测试
frontend/
src/
views/                # Home.vue/ Result.vue
components/
services/             # 前端 API 请求

```

## 快速开始
### 后端
```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
# source venv/bin/activate

pip install -r requirements.txt
python run.py
```

### 前端

```
cd frontend
npm install
npm run dev
```

### 环境变量 `.env`

```
# LLM配置
LLM_MODEL_ID=deepseek-chat
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com

# 高德地图密钥
AMAP_API_KEY=your_amap_key

# Tavily搜索（可选）
TAVILY_API_KEY=your_tavily_key
```

### 运行单元测试

```
cd backend
pytest tests/ -v
```

## 为什么拆分为 3 个 Worker？

按照业务依赖链做任务拆分，每个 Worker 具备完整业务闭环，避免无效并行：

- **ResearchWorker：玩什么**：景点搜集、RAG 知识库补充景点历史文化信息
- **LogisticsWorker：如何支撑出行**：天气、酒店、美食、路线后勤信息，依赖 Research 输出的景点集合
- **PlanningWorker：如何编排行程**：整合全部信息，做多套行程方案、预算核算，依赖前两个 Worker 输出结果

## 设计决策 & 取舍

> 
> 说明项目选型思考，也是面试口述素材

- **弃用 MCP 子进程调用高德**：Stdio 子进程存在僵尸进程、通信不稳定、调试困难问题；改为 httpx 直接 HTTP 封装，完全掌控重试、异常捕获。
- **不用 Redis**：原型阶段使用 SQLite 做会话持久化；单机部署内存缓存满足需求；多实例生产可替换 Redis。
- **不用 Neo4j 图数据库**：景点数据规模不大，高德 API + 向量检索已经满足业务，无需引入重型图数据库。
