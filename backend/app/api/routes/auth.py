"""登录鉴权接口：注册 / 登录 / 当前用户信息。"""

import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...services import user_service
from ...auth.security import hash_password, verify_password
from ...auth.jwt_utils import create_access_token
from ...auth.deps import get_optional_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

# 账号格式支持：中国大陆手机号 / 邮箱 / 用户名(3-32位)
_PHONE_RE = re.compile(r"^1\d{10}$")
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_USERNAME_RE = re.compile(r"^[\w\-\u4e00-\u9fa5]{3,32}$")


def _validate_account(account: str) -> None:
    """校验账号格式：手机号 / 邮箱 / 用户名任一合法即可。"""
    if not account:
        raise HTTPException(status_code=400, detail="账号不能为空")
    if _PHONE_RE.match(account) or _EMAIL_RE.match(account) or _USERNAME_RE.match(account):
        return
    raise HTTPException(status_code=400, detail="账号格式不正确，请使用手机号、邮箱或用户名(3-32位)")


class RegisterRequest(BaseModel):
    """注册请求体（账号支持手机号 / 邮箱 / 用户名）"""
    username: str = Field(..., min_length=3, max_length=64, description="手机号 / 邮箱 / 用户名(3-64位)")
    password: str = Field(..., min_length=6, max_length=64, description="密码(至少6位)")


class LoginRequest(BaseModel):
    """登录请求体（账号支持手机号 / 邮箱 / 用户名）"""
    username: str = Field(..., min_length=1, max_length=64, description="手机号 / 邮箱 / 用户名")
    password: str = Field(..., description="密码")


@router.post("/register", summary="用户注册")
async def register(req: RegisterRequest):
    """注册新用户，成功直接返回 token（免二次登录）。"""
    username = req.username.strip()
    _validate_account(username)
    if user_service.get_user_by_username(username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    user_id = user_service.create_user(username, hash_password(req.password))
    if user_id is None:
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")
    token = create_access_token(user_id, username)
    return {
        "success": True,
        "message": "注册成功",
        "data": {"token": token, "username": username, "user_id": user_id},
    }


@router.post("/login", summary="用户登录")
async def login(req: LoginRequest):
    """校验用户名密码，签发 JWT。"""
    username = req.username.strip()
    _validate_account(username)
    user = user_service.get_user_by_username(username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user["id"], user["username"])
    return {
        "success": True,
        "message": "登录成功",
        "data": {"token": token, "username": user["username"], "user_id": user["id"]},
    }


@router.get("/me", summary="当前用户信息")
async def me(user_id: int = Depends(get_optional_user_id)):
    """返回当前登录用户信息；未登录返回 401。"""
    if user_id is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return {"success": True, "data": user}
