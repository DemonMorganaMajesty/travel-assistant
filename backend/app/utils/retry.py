"""外部调用统一重试策略工具。

设计目标：
1. 对高德/Tavily/Unsplash 等外部 HTTP 调用统一「指数退避重试」，提升履约成功率
2. 致命错误（内容风控、Key配置错误等）重试无意义，直接跳过重试抛出/返回
3. 纯函数式封装：不侵入业务代码，调用方按需使用 async_retry 包裹

给高德、Tavily、Unsplash、MCP 这类第三方异步 IO 调用做统一的指数退避重试。
核心设计：区分致命错误 / 可重试错误；带随机抖动；重试耗尽支持兜底默认值，
避免整个 Agent 链路直接崩溃。

用法示例：
    result = await async_retry(lambda: service.search_poi(kw, city), max_retries=2, default={"status": "0"})

调用 await func()
    ↓ 成功 → 直接return结果
    ↓ 发生异常
        ├─ 判断是否【致命错误】→ 是：记录warning，直接返回default，**不重试**
        └─ 非致命（网络超时、临时503）
             attempts +=1
             超过max_retries？
                 → 是：日志error，reraise则抛异常，否则返回default
                 → 否：计算退避delay + 随机抖动，sleep之后进入下一轮循环

"""

import asyncio
import logging
import random
from typing_extensions import Callable, Awaitable, Any, Optional

from ..agent_graph.llm_errors import is_fatal_external_error

logger = logging.getLogger(__name__)


async def async_retry(
    func: Callable[[], Awaitable[Any]],
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    default: Any = None,
    label: str = "",
    reraise: bool = False,
) -> Any:
    """异步重试包装器：指数退避 + 随机抖动，致命错误直接返回 default。

    Args:
        func: 无参异步可调用对象（外部调用闭包）。
        max_retries: 最大重试次数（含首次共 max_retries+1 次尝试）。
        base_delay: 首次重试前等待秒数（指数增长）。
        max_delay: 等待上限，防止退避时间过长。
        default: 重试耗尽后的兜底返回值，避免异常向上抛导致链路失败。
        label: 日志标识，方便定位是哪个外部调用在重试。
        reraise: 重试耗尽后是否重新抛出最后一个异常（True 时忽略 default）。

    Returns:
        函数成功返回值；重试耗尽返回 default。
    """
    attempts = 0
    while True:
        try:
            return await func()
        except Exception as e:
            err_text = str(e)
            # 致命错误（风控/Key错误）：重试无意义，直接兜底返回
            if is_fatal_external_error(err_text):
                logger.warning(f"[retry] 致命错误跳过重试 label={label}: {err_text}")
                return default
            attempts += 1
            if attempts > max_retries:
                logger.error(f"[retry] 重试耗尽失败 label={label} attempts={attempts}: {err_text}")
                if reraise:
                    raise
                #default  返回空数据兜底
                return default

            delay = min(base_delay * (2 ** (attempts - 1)), max_delay)
            # 随机抖动 ±20%，防止多个请求同时重试造成流量尖峰
            jitter = random.uniform(0.8, 1.2)
            logger.warning(f"[retry] 外部调用失败将重试 label={label} 第{attempts}次 等待{delay * jitter:.1f}s: {err_text}")
            await asyncio.sleep(delay * jitter)
