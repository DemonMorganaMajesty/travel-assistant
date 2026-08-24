"""FastAPI 依赖：从请求头解析当前用户（可选鉴权）。

设计：所有接口默认匿名可用；带合法 Bearer Token 时返回 user_id，
未登录返回 None（匿名模式），方便现有功能逐步接入用户体系。

可选登录依赖项，实现「匿名可用，登录增强」模式。
"""

from typing_extensions import Optional
from fastapi import Header
from .jwt_utils import decode_access_token


def get_optional_user_id(authorization: Optional[str] = Header(default=None)) -> Optional[int]:
    """从 Authorization: Bearer <token> 中解析用户ID；未登录/无效返回 None。"""

    #  # 1.没有Authorization头，或者不是Bearer开头 → 匿名
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    # # 2.截取token字符串
    token = authorization.split(" ", 1)[1].strip()
    # 3.jwt解析，签名错误/过期返回None
    payload = decode_access_token(token)
    if not payload:
        return None
    # 4.取出sub字段转为user_id，类型异常也返回None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
