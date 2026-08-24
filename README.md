# Smart Travel Planner - LangGraph Multi-Agent System

基于 **LangChain + LangGraph** 的工业级多 Agent 旅行规划系统，采用 Supervisor-Worker-Critic 架构模式。

## 架构亮点

### Supervisor-Worker-Critic 多 Agent 协作

```
Supervisor (路由决策)
  -> ResearchWorker  (景点搜索 + RAG + 网页搜索)
  -> LogisticsWorker (天气 + 酒店 + 路线 + 美食)
  -> PlanningWorker  (预算 + 每日行程编排)
  -> Critic           (质量审查)
  -> pass -> 输出 / fail -> 重新调度
```

### 核心技术栈

| 技术 | 用途 | 业务驱动 |
|------|------|---------|
| LangGraph | 多 Agent 协作编排 | Supervisor-Worker-Critic 模式 |
| LangChain Tools | 工具定义与调用 | `@tool` 装饰器统一工具接口 |
| ChromaDB | RAG 向量检索 | 旅行攻略/历史文化知识库 |
| SQLite | 用户偏好记忆 | 记住偏好、跨会话复用 |
| FastAPI SSE | 流式推送 | 前端实时展示 Agent 思考过程 |
| Pytest | 单元测试 | 核心模块质量保障 |

### 工具矩阵

| 工具 | 业务场景 |
|------|---------|
| 高德地图 MCP | POI 搜索、路线规划、天气查询 |
| Tavily Search | 搜索景点门票/开放时间/最新攻略 |
| Fetch | 抓取攻略全文、交通时刻表 |
| RAG (ChromaDB) | 历史文化景点深度知识检索 |
| SQLite Memory | Agent 自主存取用户偏好 |

### 智能伴游对话机器人

行程生成后，用户在结果页可以通过聊天窗口与 Agent 对话，基于行程上下文回答问题、调整计划。

## 项目结构

```
backend/
  app/
    agent_graph/          # LangGraph 核心
      state.py            # AgentState 类型定义
      supervisor.py       # Supervisor 路由节点
      workers/            # Research / Logistics / Planning
      critic.py           # Critic 审查节点
      graph.py            # StateGraph 定义+编译
      companion.py        # 智能伴游对话 Agent
    tools/                # 工具层
      amap_tools.py       # 高德 MCP 工具封装
      tavily_tools.py     # Tavily 搜索
      fetch_tools.py      # Fetch 网页抓取
      rag_tools.py        # RAG 检索 (ChromaDB)
      memory_tools.py     # SQLite 记忆工具
    rag/                  # RAG 系统
      vector_store.py     # ChromaDB 管理
      embeddings.py       # Embedding 封装
      loader.py           # 文档加载/分块
      data/               # 知识库原始文档
    api/                  # API 路由
    models/               # 数据模型
  tests/                  # 测试
frontend/
  src/
    views/                # Home.vue / Result.vue
    components/
      ChatWidget.vue      # 伴游聊天组件
    services/
      api.ts              # SSE 客户端
```

## 快速开始

### 后端

```bash
cd backend
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
python run.py
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 环境变量 (.env)

```env
LLM_MODEL_ID=deepseek-chat
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
AMAP_API_KEY=your_amap_key
TAVILY_API_KEY=your_tavily_key   # 可选
```

### 运行测试

```bash
cd backend
pytest tests/ -v
```

## 为什么是 3 个 Worker？

不是简单地拆分任务。酒店、交通、美食都依赖景点位置，拆细后无法并行。3 个 Worker 基于真实的依赖链分析，每个 Worker 有完整的业务闭环：

- **ResearchWorker**: "玩什么" - 景点搜索 + 历史文化知识补充
- **LogisticsWorker**: "怎么支撑" - 天气/酒店/路线/美食 (依赖阶段1的结果)
- **PlanningWorker**: "怎么编排" - 预算/时间/每日行程 (依赖阶段1+2)

## 设计决策

- **不用 Neo4j**: 数据规模小(几十个景点)，向量检索+高德 API 已覆盖
- **不用 Redis**: SQLite 足够，单用户场景无需缓存中间件
- **不用 Puppeteer**: Fetch 已能解决网页抓取需求
- **不用 Docker**: 本地开发不需要，生产可容器化
