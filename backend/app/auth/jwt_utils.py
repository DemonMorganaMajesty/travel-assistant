"""JWT 签发与校验（PyJWT，HS256）。

生成登录 Token、解析校验 Token；所有异常全部捕获，
出错返回 None，不抛异常，适配匿名可选登录逻辑。
"""

from datetime import datetime, timedelta, timezone
from typing_extensions import Optional
import jwt

from ..config import get_settings


def create_access_token(user_id: int, username: str) -> str:
    """签发访问令牌，有效期由配置 jwt_expire_hours 控制。"""
    settings = get_settings()
    payload = {
        #禁止使用本地时区 datetime，防止服务器时区错乱导致 token 提前 / 延后失效。
        "sub": str(user_id),  # 用户ID
        "username": username,  # 用户名
        # 过期时间
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
        # 签发时间
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict]:
    """解析访问令牌；非法/过期返回 None。"""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        return None
