"""历史会话记录服务：SQLite 持久化旅游规划记录（含三方案）。

职责：
- 保存每次生成的旅行方案（request_data + 三方案plans）
- 分页查询、详情、更新标题/方案、删除
- 表：trip_history，位于 backend/data/trip_history.db

参考 memory_tools.py 的 SQLite 写法：同步sqlite3，check_same_thread=False 适配多线程。

SQLite 本地持久化行程规划记录；对应前端侧边栏历史会话：保存请求参数、多套行程方案
，支持增删改查、分页、自动生成会话标题。
"""
import json
import sqlite3
import time
from pathlib import Path
from typing_extensions import Optional, Any, List
import logging

from ..constants import HISTORY_PAGE_SIZE, HISTORY_TITLE_MAX_LEN, HISTORY_DB_FILE

logger = logging.getLogger(__name__)

# 全局缓存数据库文件路径
_DB_PATH = None


def _get_db_path() -> str:
    """获取历史会话 SQLite 数据库磁盘路径（backend/data/trip_history.db）。"""
    global _DB_PATH
    if _DB_PATH is None:
        db_dir: Path = Path(__file__).parent.parent.parent / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = str(db_dir / HISTORY_DB_FILE)
    return _DB_PATH


def _ensure_table():
    """确保 trip_history 数据表存在，不存在则创建。"""
    db_path = _get_db_path()
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trip_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                request_data TEXT NOT NULL,
                plans TEXT NOT NULL,
                active_plan_type TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            )
            """
        )


def _row_to_dict(row) -> dict:
    """把查询行转换为字典，JSON字段反序列化。"""
    if row is None:
        return None
    result = {
        "id": row[0],
        "title": row[1],
        "request_data": json.loads(row[2]) if row[2] else {},
        "plans": json.loads(row[3]) if row[3] else [],
        "active_plan_type": row[4] or "",
        "created_at": row[5],
        "updated_at": row[6],
    }
    return result


def _now() -> str:
    """当前时间字符串，格式 YYYY-MM-DD HH:MM:SS"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def auto_title(request_data: dict) -> str:
    """根据请求参数自动生成历史记录标题，如「北京 4天 2026-08-11」。"""
    city = ""
    city_list = request_data.get("city_list") or []
    if city_list:
        city = "/".join([item.get("city_name", "") for item in city_list if item.get("city_name")])
    else:
        city = request_data.get("city", "") or ""
    travel_days = request_data.get("travel_days") or 1
    start_date = request_data.get("start_date") or ""
    title = f"{city} {travel_days}天"
    if start_date:
        title += f" {start_date}"
    if not city:
        title = f"旅行规划 {start_date or travel_days}"
    return title[:HISTORY_TITLE_MAX_LEN]


def create_history(
    request_data: dict,
    plans: list,
    active_plan_type: str = "",
    title: str = "",
) -> dict:
    """保存一条历史会话记录，返回新记录字典。"""
    _ensure_table()
    if not title:
        title = auto_title(request_data or {})
    title = title[:HISTORY_TITLE_MAX_LEN] or "旅行规划"
    now = _now()
    db_path = _get_db_path()

    #sqlite3 默认：同一个连接只能创建它的线程使用；FastAPI 多线程，直接用会报错。
    #check_same_thread=False关闭线程校验，适合演示项目。
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cursor = conn.execute(
            """
            INSERT INTO trip_history (title, request_data, plans, active_plan_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                json.dumps(request_data or {}, ensure_ascii=False),
                json.dumps(plans or [], ensure_ascii=False),
                active_plan_type or "",
                now,
                now,
            ),
        )
        new_id = cursor.lastrowid
    logger.info(f"[history] 创建历史记录 id={new_id}, title={title}")
    return get_history(new_id)


def list_history(page: int = 1, page_size: int = HISTORY_PAGE_SIZE) -> dict:
    """分页查询历史记录（按更新时间倒序）。

    Returns:
        {"items": [...], "total": N, "page": page, "page_size": page_size}
    """
    _ensure_table()
    page = max(1, page)
    page_size = max(1, min(page_size, HISTORY_PAGE_SIZE))
    offset = (page - 1) * page_size
    db_path = _get_db_path()
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM trip_history")
        total = cursor.fetchone()[0]
        cursor = conn.execute(
            """
            SELECT id, title, request_data, plans, active_plan_type, created_at, updated_at
            FROM trip_history
            ORDER BY updated_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        )
        rows = cursor.fetchall()
    items = [_row_to_dict(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_history(history_id: int) -> Optional[dict]:
    """查询单条历史记录详情。"""
    _ensure_table()
    db_path = _get_db_path()
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cursor = conn.execute(
            """
            SELECT id, title, request_data, plans, active_plan_type, created_at, updated_at
            FROM trip_history WHERE id = ?
            """,
            (history_id,),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def update_history(history_id: int, title: str = None, request_data: dict = None,
                   plans: list = None, active_plan_type: str = None) -> Optional[dict]:
    """更新历史记录（标题/请求参数/方案），只更新传入的字段。"""
    _ensure_table()
    fields = []
    values = []
    if title is not None:
        fields.append("title = ?")
        values.append(str(title)[:HISTORY_TITLE_MAX_LEN])
    if request_data is not None:
        fields.append("request_data = ?")
        values.append(json.dumps(request_data, ensure_ascii=False))
    if plans is not None:
        fields.append("plans = ?")
        values.append(json.dumps(plans, ensure_ascii=False))
    if active_plan_type is not None:
        fields.append("active_plan_type = ?")
        values.append(active_plan_type)
    if not fields:
        return get_history(history_id)
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(history_id)

    db_path = _get_db_path()
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        conn.execute(
            f"UPDATE trip_history SET {', '.join(fields)} WHERE id = ?",
            values,
        )
    logger.info(f"[history] 更新历史记录 id={history_id}")
    return get_history(history_id)


def delete_history(history_id: int) -> bool:
    """删除历史记录，返回是否删除成功。"""
    _ensure_table()
    db_path = _get_db_path()
    with sqlite3.connect(db_path, check_same_thread=False) as conn:
        cursor = conn.execute("DELETE FROM trip_history WHERE id = ?", (history_id,))

        deleted = cursor.rowcount > 0
    logger.info(f"[history] 删除历史记录 id={history_id}, deleted={deleted}")
    return deleted
