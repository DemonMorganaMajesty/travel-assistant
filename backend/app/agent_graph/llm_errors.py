"""LLM/外部服务错误识别工具。

统一检测两类"重试无意义"的致命错误：
1. 内容安全风控（阿里云等模型返回 inappropriate content，重试会反复触发拦截）
2. 高德Key配置错误（USERKEY_PLAT_NOMATCH 等，重试必然失败）


_invoke_tool_safely（工具执行+重试）
    ↓捕获异常，拿到异常字符串
is_fatal_external_error(err_msg)
    ├ is_content_filter_error()
    └ is_internal_provider_error()
        → True：外部错误不重试 无意义，返回错误文本
        → False：内部错误 可以重试继续执行重试
"""

# 内容风控/敏感内容关键词（大小写不敏感匹配）
_CONTENT_FILTER_KEYWORDS = (
    "inappropriate content",
    "content filter",
    "content_filter",
    "敏感内容",
    "内容安全",
    "风控",
    "risk control",
)

# 高德等外部服务致命Key错误关键词
_FATAL_KEY_ERROR_KEYWORDS = (
    "userkey_plat_nomatch",
    "invalid_user_key",
    "key not authorized",
    "internalerror.algo",
)


def is_content_filter_error(text: str) -> bool:
    """判断错误文本是否为大模型内容安全拦截。"""
    if not text:
        return False
    t = text.lower()
    return any(keyword in t for keyword in _CONTENT_FILTER_KEYWORDS)


def is_internal_provider_error(text: str) -> bool:
    """判断模型服务商内部 5xx 错误，当前重点处理 Gemini 的 InternalError.Algo。"""
    if not text:
        return False
    t = text.lower()
    return "internalerror.algo" in t or "nonetype" in t and "group" in t


def is_fatal_external_error(text: str) -> bool:
    """判断是否为致命外部错误（重试无意义）。"""
    if not text:
        return False
    t = text.lower()
    if is_content_filter_error(text):
        return True
    # 服务商后台500类错误（InternalError.Algo/APIError）重试必然失败，直接跳过
    if is_internal_provider_error(text) or "apierror" in t:
        return True
    return any(keyword in t for keyword in _FATAL_KEY_ERROR_KEYWORDS)


# 增加服务商后端正则匹配错误
_INTERNAL_ALGO_ERROR = "internalerror.algo"
