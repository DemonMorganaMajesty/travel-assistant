# 智能旅行规划系统（Travel Assistant）技术需求文档

> 版本：v2.0 | 更新日期：2026-08-24 | 状态：迭代中

---

## 一、项目概述

### 1.1 项目背景
传统旅行规划依赖人工搜索、多平台切换与碎片化信息整合，效率低且体验割裂。本项目旨在构建一套基于 **多 Agent 协作** 的智能旅行规划系统，通过 LLM 驱动的自主 Agent 链路，实现从目的地解析、资源检索到行程编排与质量审查的全流程自动化，为用户提供可交互、可追溯、可优化的个性化行程方案。

### 1.2 项目目标
- 构建 **Supervisor-Worker-Critic** 多 Agent 协作架构，实现行程规划的自动化与可控性。
- 支持 **多城市 / 多日 / 多方案** 行程生成，并提供历史记录查询与二次优化能力。
- 集成 **RAG 混合检索 + BGE 精排**，提升景点知识问答与推荐准确性。
- 构建 **结果页智能伴游对话机器人**，支持基于行程上下文的自由问答与局部调整。
- 保证 **高可用性**：外部接口异常时自动降级，Agent 链路具备超时、重试与熔断机制。

---

## 二、业务需求

### 2.1 用户角色

| 角色 | 描述 |
|------|------|
| 普通用户（未登录） | 可输入目的地、日期生成行程方案，方案保存至本地，查看基础地图展示 |
| 注册用户（已登录） | 可保存历史方案、查看完整行程详情、使用智能伴游对话、评价方案并触发重新生成 |
| 系统管理员（运维） | 查看 Agent 链路追踪（LangFuse）、监控工具调用成功率与 Token 消耗、管理知识库文档版本 |

### 2.2 核心功能需求

| 编号 | 功能模块 | 需求描述 | 优先级 |
|------|----------|----------|--------|
| FR-01 | 行程生成入口 | 用户输入目的地、出发日期、天数、人数、预算偏好（经济/标准/舒适），Agent 自动生成完整行程方案 | P0 |
| FR-02 | 多方案生成 | 支持一次性生成 2–3 套备选方案（如“人文路线”“休闲路线”“紧凑路线”），后续方案依据前序方案反馈进行差异化优化 | P1 |
| FR-03 | 行程详情展示 | 行程包含每日景点列表（含开放时间/门票/建议游览时长）、酒店推荐、美食推荐、交通换乘建议、每日预算明细与总预算 | P0 |
| FR-04 | 地图可视化 | 行程中的景点、酒店、餐厅在地图上标注，并绘制每日路线连线 | P1 |
| FR-05 | 历史记录管理 | 已登录用户可查看、删除、重新加载历史行程方案，支持按目的地/日期检索 | P1 |
| FR-06 | 智能伴游对话 | 行程结果页提供聊天窗口，Agent 基于当前行程上下文回答用户问题（如“第二天下午能加个XX景点吗？”“附近有什么好吃的？”） | P1 |
| FR-07 | 方案评价与重生成 | 用户可对方案进行评分/反馈（如“太赶了”“预算超了”），系统触发 Critic + Planning 节点进行局部优化重生成 | P2 |
| FR-08 | 未登录降级 | 未登录用户仅可生成单次方案，不支持历史保存与伴游对话（或对话仅限当前会话） | P0 |

### 2.3 非功能需求

| 编号 | 需求描述 | 指标 |
|------|----------|------|
| NFR-01 | 单次行程生成端到端响应时间（含 Agent 推理 + 工具调用） | ≤ 60 秒（含流式输出） |
| NFR-02 | Agent 链路递归深度上限 | ≤ 30 层 |
| NFR-03 | 最大重试次数（单节点失败） | ≤ 3 次 |
| NFR-04 | 高德 API 限流策略 | 触发限流时降级为缓存/RAG 结果，不直接抛异常 |
| NFR-05 | 系统可用性（外部依赖降级后） | ≥ 99% |
| NFR-06 | 敏感内容识别与风控拦截 | 自动跳过无效重试，记录审计日志 |
| NFR-07 | 链路可观测性 | 全量接入 LangFuse，记录每个 Agent 节点的输入/输出/Token 消耗/延迟 |

---

## 三、技术架构

### 3.1 整体架构图
┌─────────────────────────────────────────────────────────────────┐
│ 前端（Vue 3） │
│ ┌────────────┐ ┌────────────┐ ┌──────────────────────────┐ │
│ │ 首页/表单 │ │ 结果页 │ │ 聊天组件 (SSE) │ │
│ └────────────┘ └────────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
│ SSE / REST
▼
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI 后端（Python 3.11+） │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ LangGraph Agent 编排层 │ │
│ │ Supervisor → ResearchWorker → LogisticsWorker → │ │
│ │ PlanningWorker → Critic → (pass/fail → 输出/重调度) │ │
│ └─────────────────────────────────────────────────────────┘ │
│ │ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 工具层（Tool Layer） │ │
│ │ 高德 MCP │ Tavily │ Fetch │ RAG │ SQLite Memory │ │
│ └─────────────────────────────────────────────────────────┘ │
│ │ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ RAG 引擎（ChromaDB + BGE） │ │
│ │ 向量语义检索 + BM25 关键词检索 → RRF 合并 → BGE 重排序 │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
│
┌───────────────────┼───────────────────┐
▼ ▼ ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ 高德 API │ │ Tavily API │ │ ChromaDB │
│ (POI/天气/ │ │ (网页搜索) │ │ (向量存储) │
│ 路线/酒店)│ │ │ │ │
└─────────────┘ └─────────────┘ └─────────────┘

text

### 3.2 技术栈选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| 后端框架 | FastAPI | 高性能异步、自动生成 OpenAPI、原生支持 SSE 流式推送 |
| Agent 编排 | LangGraph | 原生支持 StateGraph 状态管理、节点路由、循环控制与持久化，适合多 Agent 协作场景 |
| LLM 调用 | LangChain | 统一 ChatModel 接口，便于切换模型服务商（DeepSeek / OpenAI / 通义千问等） |
| 向量数据库 | ChromaDB | 轻量级嵌入式向量库，支持持久化与相似度检索，无需额外服务部署 |
| 检索增强 | RRF + BGE Reranker | 融合向量语义 + BM25 关键词召回，经 BGE 精排提升 Top-K 准确率 |
| Embedding 模型 | BGE-large-zh-v1.5 | 中文场景下效果领先，支持 1024 维向量 |
| 外部搜索 | Tavily | 专为 LLM Agent 优化的搜索 API，返回结构化网页摘要，减少无效网页抓取 |
| 地图服务 | 高德地图 MCP | 提供 POI 搜索、天气、路线规划、酒店/美食查询等旅行核心能力 |
| 可观测性 | LangFuse | 开源 LLM 可观测性平台，支持 Trace、Span、Token 统计与评分 |
| 前端框架 | Vue 3 + TypeScript | 组合式 API + 响应式数据流，适合复杂交互页面 |
| 前端 SSE | EventSource API | 接收 Agent 节点流式输出，展示"思考中→搜索中→审查中→完成"实时状态 |

---

## 四、Agent 架构详细设计

### 4.1 节点定义与职责

| 节点 | 角色 | 输入 | 输出 | 路由逻辑 |
|------|------|------|------|----------|
| **Supervisor** | 调度中枢 | 用户原始需求（目的地/日期/人数/预算） | 任务分解指令，决定启动哪些 Worker | 首次路由 → ResearchWorker；中间路由按 Critic 反馈决策 |
| **ResearchWorker** | 景点研究员 | 目的地 + 日期 | 景点列表（含坐标/门票/开放时间/建议时长）+ RAG 历史文化知识补充 | 完成 → LogisticsWorker |
| **LogisticsWorker** | 后勤规划师 | 景点列表 + 目的地 + 日期 | 每日天气、酒店推荐、美食推荐、景点间交通耗时/费用 | 完成 → PlanningWorker |
| **PlanningWorker** | 行程编排师 | 景点列表 + 后勤信息 + 预算偏好 | 每日行程表（含时间轴）+ 预算明细表 | 完成 → Critic |
| **Critic** | 质量审查员 | 完整行程方案 | 审查通过 / 修订建议（如"行程过紧""预算超支 20%"） | pass → 输出；fail → Supervisor（最多重试 2 次） |

### 4.2 状态管理（AgentState）

```python
class AgentState(TypedDict):
    # 用户输入
    destination: str
    start_date: str
    duration: int          # 天数
    travelers: int         # 人数
    budget_preference: str # economy / standard / comfortable
    
    # 中间产物
    attractions: List[Attraction]
    weather: List[DailyWeather]
    hotels: List[Hotel]
    restaurants: List[Restaurant]
    routes: List[RouteSegment]
    daily_schedule: List[DailyPlan]
    budget: Budget
    
    # 控制字段
    current_node: str
    retry_count: int
    critic_feedback: Optional[str]
    is_pass: bool
    iteration: int
    max_iterations: int  # 默认 30
4.3 循环控制与终止条件
递归上限：recursion_limit = 30，超过后强制结束并抛出友好提示。

节点重试：单个 Worker 节点失败时，最多重试 3 次（含指数退避）。

Critic 容错：Critic 审查不通过时，最多回流 Supervisor 重调度 2 次；若仍不通过，返回"审查未通过"标记，由上层决定是否展示方案（降级输出）。

工具调用超时：单个工具调用超时时间 10 秒，超时后自动重试（带随机抖动）。

4.4 工具调用可靠性设计
机制	实现方式
超时控制	asyncio.timeout 包裹工具调用，超时后抛出 TimeoutError
重试与退避	指数退避（1s → 2s → 4s）+ 随机抖动（±0.5s）
结果截断	工具返回内容超过 8000 token 时，自动截断并附注 ...（内容过长已截断）
错误分类降级	识别 403/401（Key 错误）、429（限流）、500（服务商内部错误）分别执行：跳过重试/降级为缓存/返回友好提示
风控拦截	检测用户输入含敏感词时，跳过 Agent 推理直接返回预设安全提示
五、RAG 混合检索与精排详细设计
5.1 知识库构成
数据类型	来源	存储格式
景点历史文化知识	爬取/整理的历史文化景点文档（含典故、建筑风格、游览贴士）	Markdown → 按 500 字符分块
旅行攻略	公开旅行博客/攻略文章摘要	Markdown → 按 500 字符分块
5.2 检索流程
text
用户查询（如"故宫的历史背景"）
    │
    ├─► 向量语义检索（ChromaDB，Top-20）
    │
    ├─► BM25 关键词检索（jieba 分词 + 倒排索引，Top-20）
    │
    ├─► RRF（倒数排名融合）合并为 Top-10 候选
    │
    ├─► BGE Reranker（bge-reranker-v2-m3）精排，输出 Top-5
    │
    └─► 返回给 ResearchWorker 作为上下文
5.3 降级策略
当 ChromaDB 不可用时（文件损坏/磁盘满），自动降级为纯向量检索（跳过 BM25 + RRF + BGE）。

当 Embedding 模型调用失败时，返回空检索结果，Agent 仅依赖高德 + Tavily 信息。

所有降级行为记录日志，不影响主流程完成。

六、搜索结果向量缓存设计
6.1 缓存集合划分
缓存集合	缓存内容	匹配策略	TTL
cache_amap_poi	高德 POI 搜索结果（景点/酒店/餐厅）	精确匹配（关键词 + 城市 + 类型）	7 天
cache_amap_weather	天气查询结果	精确匹配（城市 + 日期）	6 小时
cache_amap_route	路线规划结果	精确匹配（起点 + 终点 + 交通方式）	1 天
cache_tavily	Tavily 网页搜索结果	精确匹配（关键词）	3 天
cache_rag	RAG 检索结果	向量相似度匹配（阈值 ≥ 0.92）	7 天
6.2 缓存写入/读取流程
读取：工具调用前，根据参数生成缓存 Key，查询对应集合；若命中且未过期，直接返回缓存结果。

写入：外部接口调用成功后，将结果异步写入对应缓存集合（不阻塞主流程）。

限流保护：高德 API 调用前检查令牌桶；若触发限流，优先从缓存读取；若无缓存，返回延迟重试提示（不抛异常）。

七、API 设计
7.1 行程生成接口（SSE 流式）
text
POST /api/trip/generate
Content-Type: application/json

Request:
{
    "destination": "南京",
    "start_date": "2026-10-01",
    "duration": 3,
    "travelers": 2,
    "budget_preference": "standard",
    "num_plans": 2,          // 可选，生成方案数（1-3）
    "session_id": "uuid"     // 可选，未登录时自动生成
}

Response (SSE 事件流):
event: node_start
data: {"node": "Supervisor", "message": "开始分析您的出行需求..."}

event: node_progress
data: {"node": "ResearchWorker", "message": "正在搜索南京热门景点..."}

event: node_done
data: {"node": "ResearchWorker", "result": "找到 12 个景点..."}

event: plan_ready
data: {"plan_id": "plan_001", "plan": {...完整行程方案...}}

event: done
data: {"status": "success", "plan_ids": ["plan_001", "plan_002"]}
7.2 伴游对话接口（SSE 流式）
text
POST /api/trip/chat
Content-Type: application/json

Request:
{
    "plan_id": "plan_001",
    "user_message": "第二天下午能加个中山陵吗？",
    "session_id": "uuid"
}

Response (SSE 事件流):
event: message
data: {"content": "好的，我帮您检查第二天下午的时间安排..."}

event: message
data: {"content": "中山陵建议游览 2 小时，您第二天下午 14:00 后有 3 小时空档，可以加入。"}

event: done
data: {"status": "success"}
7.3 历史记录接口（REST）
方法	路径	描述
GET	/api/history	获取用户历史方案列表
GET	/api/history/{plan_id}	获取方案详情
DELETE	/api/history/{plan_id}	删除历史方案
POST	/api/history/{plan_id}/regenerate	基于反馈重新生成方案
八、前端交互设计
8.1 首页
表单输入：目的地（支持模糊搜索）、出发日期（日期选择器）、天数（1–14 天）、人数（1–20 人）、预算偏好（三段式滑块）。

生成按钮：点击后跳转至结果页，同时启动 SSE 流式生成。

未登录提示：右上角显示"登录以保存历史方案"。

8.2 结果页
顶部：行程概览（目的地 / 日期 / 天数 / 总预算）。

中左：多方案 Tab 切换（方案一 / 方案二 / 方案三）。

中右：地图展示（接入高德地图 JS API，标注每日路线）。

下方：每日行程卡片（按时间轴展开，含景点 + 交通 + 餐饮）。

右下角悬浮按钮：打开智能伴游聊天窗口（ChatWidget.vue）。

底部：评分/反馈区域（好评/差评 + 自定义意见）。

8.3 聊天组件（ChatWidget）
浮动在页面右下角，可最小化/展开。

输入框 + 发送按钮，消息列表按时间倒序排列。

消息气泡区分用户（右）和 Agent（左）。

支持流式打字机效果（通过 SSE 接收逐字内容）。

九、部署与运维需求
9.1 环境变量清单
变量名	说明	是否必须
LLM_MODEL_ID	模型 ID（如 deepseek-chat）	✅
LLM_API_KEY	模型服务商 API Key	✅
LLM_BASE_URL	模型服务商 Base URL	✅
AMAP_API_KEY	高德地图 API Key	✅
TAVILY_API_KEY	Tavily 搜索 API Key	❌
LANGFUSE_PUBLIC_KEY	LangFuse 公钥	❌
LANGFUSE_SECRET_KEY	LangFuse 私钥	❌
LANGFUSE_HOST	LangFuse Host（默认 https://cloud.langfuse.com）	❌
9.2 日志与监控
所有 Agent 节点自动接入 LangFuse Trace，记录输入/输出、Token 消耗、耗时、错误堆栈。

工具调用成功率、缓存命中率、限流触发次数输出为 metrics.log，可按日聚合分析。

系统日志级别：生产环境 INFO，开发环境 DEBUG。

9.3 本地运行方式
bash
# 后端
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py

# 前端
cd frontend
npm install
npm run dev
9.4 生产环境建议
容器化部署：Docker + Docker Compose（提供 Dockerfile 与 docker-compose.yml）。

生产环境下 ChromaDB 建议使用持久化卷挂载，防止容器重建导致知识库丢失。

高德 API 调用建议配置 Redis 分布式限流（若多实例部署）。

十、测试需求
10.1 单元测试覆盖
模块	测试覆盖内容
tools/amap_tools.py	各接口正常返回/异常降级/缓存命中/限流逻辑
tools/rag_tools.py	向量检索 + BM25 + RRF + BGE 精排全链路 / 降级链路
agent_graph/critic.py	审查通过/不通过判定逻辑
agent_graph/supervisor.py	路由决策逻辑（模拟不同状态）
tools/memory_tools.py	SQLite 读写/查询/删除
10.2 集成测试
端到端行程生成（真实 API 调用，验证完整链路 ≥ 3 个城市）。

伴游对话（基于已有方案进行 3 轮以上对话，验证上下文传递）。

多方案生成（验证后续方案与前序方案的差异化优化）。

10.3 性能测试
模拟并发 10 个用户同时生成行程，观测平均响应时间与缓存命中率。

单 Agent 链路递归深度达到上限时的强制终止表现。

十一、后续迭代规划
版本	功能	预计时间
v2.1	支持行程方案导出为 PDF / 分享链接	Q4 2026
v2.2	接入机票/火车票实时查询工具，行程中自动推荐购买时机	Q1 2027
v2.3	多语言国际化支持（英文/日文）	Q2 2027
v2.4	基于用户历史行程的个性化推荐（协同过滤 + Agent 辅助）	Q3 2027
十二、附录
A. 目录结构说明
详见项目 README 中的目录树，已包含所有核心模块路径。

B. 设计决策记录
决策	选择	理由
Agent 编排框架	LangGraph 替代 LangChain LCEL	多 Agent 协作场景下，LangGraph 的状态管理与循环控制更可控
向量数据库	ChromaDB 替代 Pinecone（云服务）	本地部署，无需额外费用；数据量小（< 10 万条），性能足够
检索策略	RRF + BGE 替代纯向量检索	实验验证：RRF+BGE 的 Top-5 准确率比纯向量检索提升 18%
会话记忆	SQLite 替代 Redis	当前用户规模小（< 100 DAU），无需引入 Redis 中间件，减少运维成本
C. 风险与应对
风险	影响	应对措施
高德 API 限流	行程生成中断或延迟	缓存策略 + 令牌桶限流 + 降级提示
模型服务商故障	全部 Agent 不可用	接入备选模型服务商（如通义千问），自动切换
递归深度超限	Agent 链路死循环	强制终止 + 返回部分生成方案 + 告警通知
ChromaDB 数据损坏	RAG 检索不可用	自动降级为纯向量检索或跳过 RAG，不影响主流程
