"""接口限流（内存滑动窗口）。

设计目标：
1. 不引入外部依赖（slowapi/redis），实现轻量内存滑动窗口限流，适合单机部署
2. 按「客户端IP + 限流分组」计数，支持不同接口不同限额（登录/规划/聊天）
3. 超过限额返回 429 + Retry-After，前端可提示"请求过于频繁，请稍后再试"

注意：
- 内存限流仅单进程有效；多实例部署时建议替换为 Redis 滑动窗口（结构同本模块）
- 窗口按秒滑动，old timestamps 惰性清理，避免内存无限增长

FastAPI 中间件，单机内存版滑动窗口限流，零第三方依赖，区分接口分组做不同 QPS 限制；
和上面exceptions.py全局异常结构保持一致，超限输出统一429返回体，携带Retry‑After响应头。
简历亮点：自研单机内存滑动窗口限流中间件，按 IP + 接口分组粒度管控；区分提交接口
、轮询接口不同配额；惰性过期清理防止内存泄漏；适配反向代理获取真实客户端 IP。
"""

import time
import threading
import logging
from typing_extensions import Dict, List, Optional, Tuple

from fastapi import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 限流窗口数据：{key: [(timestamp, ...), ...]}
_visit_history: Dict[str, List[float]] = {}
_lock = threading.Lock()

# 默认限流策略：rate = 次数 / 窗口秒数（登录与注册防爆破，规划/聊天防滥用）
DEFAULT_RATE_LIMITS: dict = {
    "auth": (10, 60),      # 登录/注册：10次/分钟
    "plan": (5, 60),       # 行程规划提交：5次/分钟
    "plan_status": (120, 60),  # 任务状态轮询：120次/分钟（轮询频率高，单独放宽）
    "chat": (30, 60),      # 伴游聊天：30次/分钟
}


def _key_for(request: Request, group: str) -> str:
    """限流 key：客户端IP + 限流分组。"""
    # 兼容反向代理：优先取 X-Forwarded-For 首个IP，否则用连接端IP
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else "unknown"
    return f"{group}:{client_ip}"


def _cleanup(group_key: str, window: int, now: float) -> None:
    """清理窗口外的旧时间戳。"""
    hits = _visit_history.get(group_key, [])
    _visit_history[group_key] = [t for t in hits if now - t < window]



class RateLimitMiddleware:
    """FastAPI 中间件：按分组限流，超限返回 429 + Retry-After。"""

    def __init__(self, app, limits: Optional[dict] = None):
        self.app = app
        self.limits = limits or DEFAULT_RATE_LIMITS

    async def __call__(self, scope, receive, send):
        from starlette.requests import Request as StarletteRequest
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = StarletteRequest(scope, receive)
        path = request.url.path
        group = self._match_group(path)
        if group is None:
            await self.app(scope, receive, send)
            return
        limit, window = self.limits.get(group, (10, 60))
        key = _key_for(request, group)
        now = time.time()
        with _lock:
            _cleanup(key, window, now)
            hits = _visit_history.setdefault(key, [])
            hits.append(now)
            if len(hits) > limit:
                oldest = hits[0]
                retry_after = int(window - (now - oldest)) + 1 if oldest else window
                logger.warning(f"[rate_limit] 触发限流 group={group} key={key} limit={limit}/{window}s")
                response = JSONResponse(
                    status_code=429,
                    content={
                        "code": 429,
                        "message": "请求过于频繁，请稍后再试",
                        "data": None,
                        "detail": "请求过于频繁，请稍后再试",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    def _match_group(path: str) -> Optional[str]:
        """按路径前缀分配限流分组。"""
        if "/auth" in path:
            return "auth"
        # 任务状态轮询单独分组：轮询频率高（每1-2秒一次），不能与提交共用限额
        if "/trip/plan/task/" in path:
            return "plan_status"
        if "/trip/plan" in path:
            return "plan"
        if "/trip/chat" in path:
            return "chat"
        return None
