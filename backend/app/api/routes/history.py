"""历史会话记录 API 路由：增删改查旅游规划记录（含三方案）。

提供：
- GET  /api/history?page=1&page_size=10   分页查询
- GET  /api/history/{id}                 查看详情
- POST /api/history                      新建记录（前端生成方案后自动保存）
- PUT  /api/history/{id}                 更新标题/方案
- DELETE /api/history/{id}               删除记录
"""
from typing_extensions import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...services import history_service
from ...constants import HISTORY_PAGE_SIZE

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["历史会话记录"])


class HistoryCreate(BaseModel):
    """新建历史记录请求体"""
    title: Optional[str] = Field(default="", description="标题，空则自动生成")
    request_data: dict = Field(default={}, description="生成方案时的请求参数")
    plans: List[dict] = Field(default=[], description="三方案列表")
    active_plan_type: str = Field(default="", description="当前选中的方案类型")


class HistoryUpdate(BaseModel):
    """更新历史记录请求体（只更新传入字段）"""
    title: Optional[str] = Field(default=None, description="新标题")
    request_data: Optional[dict] = Field(default=None, description="请求参数")
    plans: Optional[List[dict]] = Field(default=None, description="三方案列表")
    active_plan_type: Optional[str] = Field(default=None, description="当前选中的方案类型")


@router.get("", summary="分页查询历史会话记录")
async def list_history(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(HISTORY_PAGE_SIZE, ge=1, le=HISTORY_PAGE_SIZE, description="每页条数(最多10条)"),
):
    """分页查询历史记录，每页最多10条，按更新时间倒序。"""
    try:
        data = history_service.list_history(page=page, page_size=page_size)
        return {"success": True, "message": "查询成功", "data": data}
    except Exception as e:
        logger.error(f"[history] 分页查询失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询历史记录失败: {str(e)}")


@router.get("/{history_id}", summary="查询历史会话记录详情")
async def get_history(history_id: int):
    """查询单条历史记录（含三方案）。"""
    try:
        record = history_service.get_history(history_id)
        if record is None:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return {"success": True, "message": "查询成功", "data": record}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[history] 查询详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询历史记录失败: {str(e)}")


@router.post("", summary="新建历史会话记录")
async def create_history(request: HistoryCreate):
    """保存一条新的旅游规划记录（前端生成方案后自动调用）。"""
    try:
        record = history_service.create_history(
            request_data=request.request_data,
            plans=request.plans,
            active_plan_type=request.active_plan_type,
            title=request.title or "",
        )
        return {"success": True, "message": "保存成功", "data": record}
    except Exception as e:
        logger.error(f"[history] 新建失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存历史记录失败: {str(e)}")


@router.put("/{history_id}", summary="更新历史会话记录")
async def update_history(history_id: int, request: HistoryUpdate):
    """更新历史记录的标题/请求参数/方案。"""
    try:
        record = history_service.update_history(
            history_id=history_id,
            title=request.title,
            request_data=request.request_data,
            plans=request.plans,
            active_plan_type=request.active_plan_type,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return {"success": True, "message": "更新成功", "data": record}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[history] 更新失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新历史记录失败: {str(e)}")


@router.delete("/{history_id}", summary="删除历史会话记录")
async def delete_history(history_id: int):
    """删除一条历史会话记录。"""
    try:
        deleted = history_service.delete_history(history_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return {"success": True, "message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[history] 删除失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除历史记录失败: {str(e)}")
