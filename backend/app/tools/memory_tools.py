"""基于 SQLite 的用户偏好记忆工具。
跨会话存储和检索用户偏好。
同步SQLite；在LangGraph异步环境建议使用sync_to_async包装调用。
表：user_memory，存储键‑值格式用户出行偏好。
"""
import json
import sqlite3
import os
from pathlib import Path
import logging
from typing_extensions import Optional
from langchain_core.tools import tool

# 模块日志
logger = logging.getLogger(__name__)

# 全局缓存数据库文件路径
_DB_PATH = None

# 用户偏好档案的 key 前缀：user:{user_id}:profile
_USER_PROFILE_KEY = "user:{}:profile"


def load_user_profile(user_id: str) -> Optional[dict]:
    """按用户加载偏好档案；未登录或未保存过返回 None。"""
    if not user_id:
        return None
    try:
        _ensure_table()
        db_path = _get_db_path()
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            row = conn.execute(
                "SELECT value FROM user_memory WHERE key = ?",
                (_USER_PROFILE_KEY.format(user_id),),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])
    except Exception as e:
        logger.warning(f"[load_user_profile] 读取失败 user_id={user_id}: {e}")
        return None


def save_user_profile(user_id: str, data: dict) -> bool:
    """按用户保存偏好档案（幂等覆盖）。"""
    if not user_id:
        return False
    try:
        _ensure_table()
        db_path = _get_db_path()
        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_memory (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (_USER_PROFILE_KEY.format(user_id), json.dumps(data, ensure_ascii=False)),
            )
        return True
    except Exception as e:
        logger.warning(f"[save_user_profile] 写入失败 user_id={user_id}: {e}")
        return False


def _get_db_path() -> str:
    """获取 SQLite 数据库磁盘路径。
    向上回溯三级，定位到backend/data/user_memory.db
    """
    global _DB_PATH
    if _DB_PATH is None:
        # __file__ 当前py文件，向上3层到达backend目录
        db_dir: Path = Path(__file__).parent.parent.parent / "data"
        # parents=True 多级目录不存在自动创建；exist_ok=True存在不报错
        db_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = str(db_dir / "user_memory.db")
    logger.debug(f"[user_memory] sqlite数据库路径: {_DB_PATH}")
    return _DB_PATH


def _ensure_table():
    """确保 user_memory 数据表已经创建，不存在则新建。
    CREATE TABLE IF NOT EXISTS 幂等，重复调用不会报错。
    """
    db_path = _get_db_path()
    # check_same_thread=False：适配LangGraph多线程调用，生产sqlite注意不要高并发写
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memory (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # with上下文退出自动commit、close，无需手动写commit/close


@tool
def save_user_preference(key: str, value: str) -> str:
    """保存用户偏好到持久化记忆。
    适合保存：酒店预算、饮食口味、出行爱好、住宿要求等信息。

    Args:
        key: 偏好键名（如 "hotel_budget"、"food_preference"）。
        value: 偏好值（如 "500"、"辣味食物"）。

    Returns:
        json字符串确认保存状态。
    """
    # 参数校验
    if not key or not isinstance(key, str):
        err_msg = "参数错误：key不能为空字符串"
        logger.warning(f"[save_user_preference] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)
    if len(key) > 64:
        err_msg = "参数错误：key长度不能超过64字符"
        logger.warning(f"[save_user_preference] {err_msg}, key={key}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    try:
        _ensure_table()
        db_path = _get_db_path()
        logger.info(f"[save_user_preference] 保存偏好 key={key}, value={value}")

        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            # INSERT OR REPLACE：key主键冲突直接覆盖旧value，实现更新
            conn.execute(
                "INSERT OR REPLACE INTO user_memory (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value),
            )
            # with块结束自动commit和关闭连接

        return json.dumps({"status": "已保存", "key": key, "value": value}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[save_user_preference] 数据库异常 key={key}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def get_user_preference(key: str) -> str:
    """从持久化记忆中检索用户偏好。

    Args:
        key: 要查找的偏好键名。

    Returns:
        存储的偏好值；未找到返回value为null。
    """
    if not key:
        err_msg = "参数错误：key不能为空字符串"
        logger.warning(f"[get_user_preference] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    try:
        _ensure_table()
        db_path = _get_db_path()
        logger.debug(f"[get_user_preference] 查询偏好 key={key}")

        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            cursor = conn.execute("SELECT value FROM user_memory WHERE key = ?", (key,))
            row = cursor.fetchone()

        if row:
            return json.dumps({"key": key, "value": row[0]}, ensure_ascii=False)
        return json.dumps({"key": key, "value": None}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[get_user_preference] 数据库异常 key={key}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def list_user_preferences() -> str:
    """列出所有已保存的用户偏好，按更新时间倒序。

    Returns:
        包含所有偏好键值对的 JSON 对象。
    """
    try:
        _ensure_table()
        db_path = _get_db_path()
        logger.info("[list_user_preferences] 查询全部用户偏好")

        with sqlite3.connect(db_path, check_same_thread=False) as conn:
            cursor = conn.execute("SELECT key, value FROM user_memory ORDER BY updated_at DESC")
            rows = cursor.fetchall()

        # list转字典 {key:value}
        prefs = {row[0]: row[1] for row in rows}
        return json.dumps(prefs, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error("[list_user_preferences] 数据库异常", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)