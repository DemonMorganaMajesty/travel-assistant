"""后台任务服务（内存实现）：行程规划异步化（方案B）。

职责：
1. 把耗时行程规划提交为后台任务，前端轮询状态而非长连接 SSE
2. 任务状态机：pending -> running -> success / failed
3. 幂等支持：相同 idempotency_key 复用已提交任务，避免重复生成
4. 内存 TTL 清理：过期任务惰性清理，防止内存无限增长

行程规划耗时计算异步任务方案（轮询模式，替代 SSE 长连接）。
前端不再 SSE 流式监听，改为：提交任务 → 获取task_id →
前端循环轮询/api/task/{task_id}接口拿状态，直到success/failed拿到结果。

适用范围：单进程部署；多实例时建议替换为 Redis 任务存储（接口保持一致）。
"""

import time
import uuid
import logging
import threading
from typing_extensions import Dict, Optional, Any

logger = logging.getLogger(__name__)

# 任务状态常量
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_SUCCESS = "success"
TASK_FAILED = "failed"

# 任务 TTL（秒）：超过后惰性清理
TASK_TTL_SECONDS: int = 60 * 60  # 1小时

# 任务存储：{task_id: task_dict}
_tasks: Dict[str, dict] = {}
# 幂等索引：{idempotency_key: task_id}
_idempotent_index: Dict[str, str] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.time()


def create_task(idempotency_key: Optional[str] = None) -> tuple:
    """创建后台任务，返回 (task_id, is_new)。


     用户连续多次点击提交，前端传同一个 key；后端不会创建多个任务，
     避免重复消耗 LLM token 与第三方 API 配额。
    - 幂等：传入 idempotency_key 且已存在未过期任务时，直接复用旧任务（is_new=False）
    - 否则新建任务（is_new=True）

    """
    with _lock:
        _cleanup_expired()
        if idempotency_key:
            existing = _idempotent_index.get(idempotency_key)
            if existing and existing in _tasks:
                logger.info(f"[task_service] 幂等命中 idempotency_key={idempotency_key} -> task={existing}")
                return existing, False

        task_id = uuid.uuid4().hex
        now = _now()
        task = {
            "task_id": task_id,
            "status": TASK_PENDING,
            "progress": 0,
            "node": "",
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "idempotency_key": idempotency_key,
        }
        _tasks[task_id] = task
        if idempotency_key:
            _idempotent_index[idempotency_key] = task_id
        logger.info(f"[task_service] 创建任务 task_id={task_id} idempotency_key={idempotency_key}")
        return task_id, True


def update_task(task_id: str, **kwargs) -> None:
    """更新任务字段（status/progress/node/result/error），自动维护 updated_at。"""
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        for key, value in kwargs.items():
            if key in task:
                task[key] = value
        task["updated_at"] = _now()


def get_task(task_id: str) -> Optional[dict]:
    """查询任务快照（拷贝返回，防止外部直接改内部状态）。"""
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        _cleanup_expired()
        # 过期任务视为不存在
        if _now() - task["updated_at"] > TASK_TTL_SECONDS:
            _tasks.pop(task_id, None)
            return None
        return dict(task)


def _cleanup_expired() -> None:
    """清理过期任务与幂等索引（惰性：仅在创建/查询时触发）。
    惰性：读写的时候顺带清理过期任务，不用开启额外后台线程，代码简单。缺点：没有访问的时候，
    过期任务会残留在内存，直到下一次接口调用。生产一般用 Redis TTL 自动淘汰。
    """
    now = _now()
    expired = [tid for tid, t in _tasks.items() if now - t["updated_at"] > TASK_TTL_SECONDS]
    for tid in expired:
        t = _tasks.pop(tid, None)
        if t and t.get("idempotency_key"):
            _idempotent_index.pop(t["idempotency_key"], None)
    if expired:
        logger.info(f"[task_service] 清理过期任务 {len(expired)} 个")
