"""Tavily 搜索工具，用于网页搜索。
LangChain异步Tool，调用Tavily搜索API获取实时互联网旅行信息。
适合查询门票、开放时间、近期活动、最新攻略；弥补大模型知识截止时间。
"""
import json
import os
import logging
from langchain_core.tools import tool
from ..rag.search_cache import cache_lookup, cache_store
from ..utils.retry import async_retry

logger = logging.getLogger(__name__)

# 常量配置，方便后续统一修改
TAVILY_API_URL = "https://api.tavily.com/search"
SEARCH_DEPTH_BASIC = "basic"
# tavily官方max_results合理范围 1‑10
MAX_RESULTS_UPPER = 10
MAX_RESULTS_LOWER = 1


@tool
async def tavily_search(query: str, max_results: int = 3) -> str:
    """通过 Tavily 搜索引擎检索最新的旅行信息。

    适用场景：
    - 最新的门票价格和开放时间
    - 近期的旅行攻略和评价
    - 当前的节庆活动
    - LLM 训练数据可能未覆盖的实时信息

    Args:
        query: 搜索查询（如 "故宫 2025 门票价格 开放时间"）。
        max_results: 最多返回的结果数（默认 3）。

    Returns:
        包含搜索结果的 JSON 字符串。
    """
    # =========参数校验与边界保护=========
    if not query or not isinstance(query, str):
        err_msg = "参数错误：搜索query不能为空"
        logger.warning(f"[tavily_search] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    # 限制返回结果数量，防止LLM传入非法数值
    max_results = max(MAX_RESULTS_LOWER, min(max_results, MAX_RESULTS_UPPER))
    logger.info(f"[tavily_search] 发起搜索 query={query}, max_results={max_results}")

    # 搜索前先查向量缓存：命中直接复用，避免重复调用Tavily API
    cache_query = f"{query} (max_results={max_results})"
    cached = cache_lookup("tavily", cache_query)
    if cached is not None:
        logger.info(f"[tavily_search] 命中Tavily向量缓存 query={query[:60]}")
        return json.dumps(cached, ensure_ascii=False)

    try:
        # httpx延迟导入，只有工具调用才加载http库
        import httpx

        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            err_msg = "Tavily API 密钥未配置。请在 .env 中设置 TAVILY_API_KEY"
            logger.warning(f"[tavily_search] {err_msg}")
            return json.dumps({"error": err_msg}, ensure_ascii=False)

        # 异步http客户端，超时30秒，避免卡死；网络瞬时错误自动重试（指数退避）
        async def _do_search() -> dict:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": SEARCH_DEPTH_BASIC,
                }
                response = await client.post(TAVILY_API_URL, json=payload)
                # 4xx/5xx抛出HTTPStatusError
                response.raise_for_status()
                return response.json()

        results = await async_retry(_do_search, max_retries=2, base_delay=1.0, max_delay=4.0, label="tavily")
        logger.info(f"[tavily_search] API请求成功，获取原始结果条数:{len(results.get('results', []))}")

        simplified = []
        for r in results.get("results", []):
            item = {
                "title": r.get("title", ""),
                "content": r.get("content", "")[:1200],  # 截断单条内容，防止超长token
                "url": r.get("url", ""),
            }
            simplified.append(item)

        # 有用搜索结果写入向量库，供后续搜索复用
        cache_store("tavily", cache_query, {"results": simplified}, {"query": query})
        return json.dumps({"results": simplified}, ensure_ascii=False, indent=2)

    except httpx.TimeoutException:
        err_msg = "Tavily搜索API请求超时"
        logger.error(f"[tavily_search] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except httpx.HTTPStatusError as e:
        err_msg = f"Tavily API返回异常状态码:{e.response.status_code}"
        logger.error(f"[tavily_search] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except json.JSONDecodeError:
        err_msg = "Tavily返回非合法JSON数据"
        logger.error(f"[tavily_search] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    except Exception as e:
        err_msg = f"Tavily 搜索失败: {str(e)}"
        logger.error(f"[tavily_search] {err_msg}", exc_info=True)
        return json.dumps({"error": err_msg}, ensure_ascii=False)