"""用户账户服务（SQLite）。

表：users(id, username, password_hash, created_at)
"""

import sqlite3
from pathlib import Path
from typing_extensions import Optional, Dict
import logging

logger = logging.getLogger(__name__)

_DB_PATH = None


def _get_db_path() -> str:
    """定位 backend/data/users.db 并确保目录存在。"""
    global _DB_PATH
    if _DB_PATH is None:
        db_dir = Path(__file__).parent.parent.parent / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = str(db_dir / "users.db")
    return _DB_PATH


def _ensure_table() -> None:
    """幂等建表。"""
    with sqlite3.connect(_get_db_path(), check_same_thread=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def create_user(username: str, password_hash: str) -> Optional[int]:
    """创建用户，成功返回 user_id；用户名重复返回 None。"""
    try:
        _ensure_table()
        with sqlite3.connect(_get_db_path(), check_same_thread=False) as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        logger.warning(f"[user_service] 用户名已存在: {username}")
        return None
    except Exception as e:
        logger.error(f"[user_service] 创建用户异常: {e}", exc_info=True)
        return None


def get_user_by_username(username: str) -> Optional[Dict]:
    """按用户名查用户。"""
    try:
        _ensure_table()
        with sqlite3.connect(_get_db_path(), check_same_thread=False) as conn:
            row = conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}
    except Exception as e:
        logger.error(f"[user_service] 查询用户异常: {e}", exc_info=True)
        return None


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """按 ID 查用户（不含密码哈希）。"""
    try:
        _ensure_table()
        with sqlite3.connect(_get_db_path(), check_same_thread=False) as conn:
            row = conn.execute(
                "SELECT id, username FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1]}
    except Exception as e:
        logger.error(f"[user_service] 查询用户异常: {e}", exc_info=True)
        return None
