"""统一 API 错误码与异常响应结构。

设计目标：
1. 所有接口错误统一返回 {code, message, data} 结构，方便前端统一处理
2. HTTPException / 参数校验错误 / 未捕获异常 集中转成统一结构，避免前端拿到裸 500
3. 保留 detail 字段兼容旧前端（Result/Home 等已有代码读取 response.data.detail）


FastAPI 全局异常拦截，全部错误输出固定 {code,message,data,detail} JSON 格式，
前端不需要分别处理不同类型报错；屏蔽原始 500 堆栈不对外暴露，同时兼容旧前端detail字段。
属于后端工程化亮点，简历可以写：FastAPI 全局统一异常中间件，业务自定义异常，参数校验、
HTTP 异常、未捕获异常收口，前后端错误契约，屏蔽服务端堆栈泄露

"""

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

logger = logging.getLogger(__name__)

# 全局错误码约定：业务码为数字，HTTP状态码与错误码语义一一对应
# 可通过 code 精确判断错误类型，而不是依赖解析 status_code
CODE_OK = 0
CODE_VALIDATION_ERROR = 400
CODE_UNAUTHORIZED = 401
CODE_FORBIDDEN = 403
CODE_NOT_FOUND = 404
CODE_RATE_LIMITED = 429
CODE_INTERNAL_ERROR = 500


class ApiError(Exception):
    """业务异常：携带错误码、提示信息与可选数据，被全局 handler 转为统一结构。"""

    def __init__(self, code: int = CODE_INTERNAL_ERROR, message: str = "服务器内部错误", data=None, status_code: int = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        # 未显式指定 HTTP 状态码时按错误码推断
        self.status_code = status_code or (code if 400 <= code < 600 else CODE_INTERNAL_ERROR)


def _unified_body(message: str, code: int, data=None) -> dict:
    """构造统一响应体。保留 detail 字段做旧前端兼容。"""
    return {
        "code": code,
        "message": message,
        "data": data,
        "detail": message,  # 兼容旧前端：读取 response.data.detail 提示错误
    }


def register_exception_handlers(app) -> None:
    """注册全局异常处理器到 FastAPI 应用。"""
    #原生HTTPException，例如raise HTTPException(status_code=404)，转为统一返回体。
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    # Pydantic 参数校验错误转为统一返回体。
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    # 自己写的业务异常，直接使用异常内的 code、message、data 输出。
    app.add_exception_handler(ApiError, _api_error_handler)
    # 其他未捕获的异常转为统一返回体。
    app.add_exception_handler(Exception, _unhandled_exception_handler)


async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTPException -> 统一结构（保留原 status_code 与 detail）。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=_unified_body(str(exc.detail), exc.status_code),
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 参数校验错误 -> 400 统一结构，附首条错误信息便于定位。"""
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", [])) if first else ""
    msg = f"参数校验失败: {loc} {first.get('msg', '')}".strip()
    logger.warning(f"[errors] 参数校验错误 {msg} body={exc.body}")
    return JSONResponse(
        status_code=CODE_VALIDATION_ERROR,
        content=_unified_body(msg, CODE_VALIDATION_ERROR, {"errors": errors}),
    )


async def _api_error_handler(request: Request, exc: ApiError):
    """业务 ApiError -> 统一结构。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=_unified_body(exc.message, exc.code, exc.data),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception):
    """兜底处理器：未捕获异常统一返回 500，避免泄露堆栈信息。"""
    logger.exception(f"[errors] 未捕获异常 path={request.url.path}")
    return JSONResponse(
        status_code=CODE_INTERNAL_ERROR,
        content=_unified_body("服务器内部错误，请稍后重试", CODE_INTERNAL_ERROR),
    )
