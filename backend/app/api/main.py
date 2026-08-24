"""FastAPI主应用
整个后端服务程序入口，uvicorn 启动入口；负责：中间件加载、路由注册、
启动 / 关闭生命周期钩子、健康检查、配置校验、RAG 知识库后台初始化。

浏览器前端请求
↓
RateLimitMiddleware（内存滑动窗口限流，超限直接429返回）
↓
CORSMiddleware跨域处理
↓
路由分发到对应接口（trip.py）
↓
接口层做参数Pydantic校验
↓
调用LangGraph graph.invoke/astream
    ↓ Agent内部：state、supervisor → research/logistics/planning/critic worker
    ↓ worker内部捕获工具、LLM异常，内部降级，不向外抛异常
↓ 返回SSE / JSON响应
↓ 如果代码抛出异常 → register_exception_handlers 全局异常捕获，输出统一 {code,message,data}
↓ 返回给前端

"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings, validate_config, print_config
from .routes import trip, poi, map as map_routes, history, auth
from .errors import register_exception_handlers
from .rate_limit import RateLimitMiddleware
import logging
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

# ----------------------全局日志配置----------------------
logger = logging.getLogger(__name__)

# 获取配置
settings = get_settings()

# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="智能旅行规划助手API",
    docs_url="/docs", # Swagger交互式文档访问路径
    redoc_url="/redoc" # ReDoc静态文档访问路径
)

#三个中间件的顺序不能乱
#请求进来先过限流 → 跨域处理 → 路由函数执行业务逻辑 → 发生异常进入全局异常 handler
# 配置CORS跨域中间件，允许前端网页跨域调用后端接口
# 接口限流中间件：登录/规划/聊天防滥用（内存滑动窗口，按 IP+分组计数）
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),  # 允许的前端域名列表，从配置读取
    allow_credentials=True,  # 允许携带Cookie、凭证
    allow_methods=["*"],  # 允许全部HTTP方法 GET/POST/PUT/DELETE
    allow_headers=["*"],  # 允许全部请求头
)

# 注册业务路由，全部接口统一加上 /api 前缀
app.include_router(trip.router, prefix="/api")      # 行程相关接口
app.include_router(poi.router, prefix="/api")       # POI景点查询接口
app.include_router(map_routes.router, prefix="/api")# 地图高德相关接口
app.include_router(history.router, prefix="/api")   # 历史会话记录接口
app.include_router(auth.router, prefix="/api")      # 登录鉴权接口

# 全局统一异常响应：HTTPException/参数校验/未捕获异常转为 {code, message, data} 结构
register_exception_handlers(app)

@app.on_event("startup")
async def startup_event():
    """
    应用启动钩子，uvicorn服务启动完成后、接收请求之前执行
    适合：配置校验、初始化大模型、初始化数据库连接池
    """
    print("\n" + "="*60)
    print(f"🚀 {settings.app_name} v{settings.app_version}")
    print("="*60)
    
    # 打印配置信息
    print_config()
    
    # 验证配置
    try:
        validate_config()
        print("\n✅ 配置验证通过")
        logger.info("应用启动：配置校验全部通过")
    except ValueError as e:
        print(f"\n❌ 配置验证失败:\n{e}")
        print("\n请检查.env文件并确保所有必要的配置项都已设置")
        logger.critical(f"配置校验失败: {e}")
        # 抛出异常，服务直接终止，不允许启动
        raise
    
    # 后台异步构建 RAG 知识库（不阻塞服务启动）：把 data 下攻略文档向量化入库
    import asyncio
    asyncio.create_task(_build_rag_knowledge_base())

    print("\n" + "="*60)
    print("📚 API文档: http://localhost:8000/docs")
    print("📖 ReDoc文档: http://localhost:8000/redoc")
    print("="*60 + "\n")


async def _build_rag_knowledge_base():
    """后台异步构建RAG向量知识库。

    将 app/rag/data 下的攻略文档分块并写入 ChromaDB（backend/data/chromadb），
    构建失败不影响主服务，仅记录警告。
    """
    try:
        import asyncio
        from ..rag.loader import build_knowledge_base
        from ..rag.vector_store import get_vector_store

        # 知识库已有内容则跳过重建，避免每次启动重复入库/误删已有数据
        try:
            existing_count = get_vector_store()._collection.count()
        except Exception as count_err:
            logger.warning(f"读取知识库数量失败，按空库处理: {count_err}")
            existing_count = 0
        if existing_count > 0:
            logger.info(f"RAG知识库已存在（{existing_count}个分块），跳过重建")
            return

        logger.info("开始后台构建RAG知识库...")
        # to_thread：把同步阻塞的向量入库放到线程池，避免卡住事件循环
        chunk_count = await asyncio.to_thread(build_knowledge_base)
        logger.info(f"RAG知识库构建完成，入库分块数: {chunk_count}")
    except Exception as e:
        logger.warning(f"RAG知识库构建失败（不影响主服务）: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """
    应用关闭钩子：服务收到终止信号(SIGINT/SIGTERM)触发
    适合关闭数据库、连接池，释放资源
    """
    print("\n" + "="*60)
    print("👋 应用正在关闭...")
    print("="*60 + "\n")


@app.get("/")
async def root():
    """根路径，访问服务根地址返回服务基础信息"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health():
    """
    健康检查接口，给容器编排、监控工具使用
    容器/K8s会定时GET此接口，判断服务存活
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        # reload=True仅开发模式，代码改动自动重启；生产务必关闭reload
        reload=True
    )

