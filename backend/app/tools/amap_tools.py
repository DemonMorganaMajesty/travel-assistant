"""高德地图工具封装为 LangChain Tool。

通过 AmapService 直连高德开放平台 REST API（httpx），
提供 POI 搜索、天气查询和路线规划。

说明：原实现通过 fastmcp StdioTransport 每次新起 amap-mcp-server 子进程，
服务器文件缺失/进程频繁启停导致连接关闭、拿不到 POI 与天气数据；
现改为复用 AmapService 单例直接请求高德 REST 接口，稳定且不阻塞事件循环。
工具全部为异步async，适配LangGraph异步Agent调用。
"""
import json
import logging
from typing_extensions import Optional
from langchain_core.tools import tool

from ..services.amap_service import get_amap_service
from ..rag.search_cache import cache_lookup, cache_store

# 配置本模块日志
logger = logging.getLogger(__name__)

# 单次搜索最多返回的POI条数
MAX_POI_RESULTS = 10


def _error_response(tool_name: str, err) -> str:
    """统一构造高德工具调用失败的错误JSON"""
    return json.dumps(
        {"error": f"高德 {tool_name} 调用失败: {str(err)}"},
        ensure_ascii=False,
    )


def _format_pois(pois: list) -> list:
    """精简POI字段，只保留LLM编排需要的信息，节省token"""
    simplified = []
    for p in pois[:MAX_POI_RESULTS]:
        simplified.append({
            "name": p.get("name", ""),
            "address": p.get("address", ""),
            "location": p.get("location", ""),
            "type": p.get("type", ""),
            "tel": p.get("tel", ""),
        })
    return simplified


@tool
async def amap_text_search(keywords: str, city: str, citylimit: bool = True) -> str:
    """
    通过高德地图在指定城市中搜索 POI（景点、酒店、餐厅、旅游地点）。
    适合Agent查找目的地、住宿、美食地点。

    Args:
        keywords: 搜索关键词（如 "景点"、"酒店"、"美食"）。
        city: 城市名称（如 "北京"、"乌鲁木齐"）。
        citylimit: 是否强制限制搜索结果仅在该城市范围内，默认True。

    Returns:
        包含搜索POI列表的 JSON 字符串。
    """
    if not keywords or not city:
        err_msg = "参数错误：keywords与city不能为空"
        logger.warning(f"[amap_text_search] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    logger.info(f"[amap_text_search] 搜索POI keywords={keywords}, city={city}, citylimit={citylimit}")

    # 搜索前先查向量缓存：命中直接复用，避免重复调用高德API
    cache_query = f"{keywords} {city}"
    cached = cache_lookup("amap_poi", cache_query)

    if cached is not None:
        logger.info(f"[amap_text_search] 命中POI向量缓存 keywords={keywords}, city={city}")
        return json.dumps(cached, ensure_ascii=False)

    try:
        service = get_amap_service()
        result = await service.async_search_poi(keywords, city, citylimit)
    except Exception as e:
        logger.exception("[amap_text_search] 调用异常")
        return _error_response("maps_text_search", e)

    if result.get("status") != "1":
        return json.dumps({
            "error": f"高德 maps_text_search 业务失败: {result.get('info', 'unknown')}",
            "pois": [],
        }, ensure_ascii=False)

    pois = _format_pois(result.get("pois", []))
    logger.info(f"[amap_text_search] 获取POI {len(pois)} 条")
    # 有用搜索结果写入向量库，供后续搜索复用
    cache_store("amap_poi", cache_query, {"pois": pois}, {"city": city, "keywords": keywords})
    return json.dumps({"pois": pois}, ensure_ascii=False, indent=2)


@tool
async def amap_weather(city: str) -> str:
    """
    通过高德地图获取城市天气预报，用于旅行规划时参考天气。

    Args:
        city: 城市名称（如 "北京"）。

    Returns:
        包含天气预报数据的 JSON 字符串。
    """
    if not city:
        err_msg = "参数错误：city城市名不能为空"
        logger.warning(f"[amap_weather] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    logger.info(f"[amap_weather] 查询天气 city={city}")

    # 搜索前先查向量缓存：天气24小时内有效，命中直接复用
    cached = cache_lookup("amap_weather", city)
    if cached is not None:
        logger.info(f"[amap_weather] 命中天气向量缓存 city={city}")
        return json.dumps(cached, ensure_ascii=False)

    try:
        service = get_amap_service()
        result = await service.async_get_weather(city)
    except Exception as e:
        logger.exception("[amap_weather] 调用异常")
        return _error_response("maps_weather", e)

    if result.get("status") != "1":
        return json.dumps({
            "error": f"高德 maps_weather 业务失败: {result.get('info', 'unknown')}",
            "forecasts": [],
        }, ensure_ascii=False)

    forecasts = result.get("forecasts", [])
    logger.info(f"[amap_weather] 获取预报 {len(forecasts)} 条")
    # 有用搜索结果写入向量库，供后续搜索复用
    cache_store("amap_weather", city, {"forecasts": forecasts}, {"city": city})
    return json.dumps({"forecasts": forecasts}, ensure_ascii=False, indent=2)


@tool
async def amap_route(
    origin_address: str,
    destination_address: str,
    route_type: str = "driving",
    origin_city: Optional[str] = None,
    destination_city: Optional[str] = None,
) -> str:
    """
    通过高德地图规划两地之间的出行路线，支持驾车、步行、公共交通。

    Args:
        origin_address: 出发详细地址。
        destination_address: 目的详细地址。
        route_type: 路线类型 - "walking"（步行）、"driving"（驾车）或 "transit"（公交）。
        origin_city: 出发城市（可选，提高地址解析精度）。
        destination_city: 目的城市（可选，提高地址解析精度）。

    Returns:
        包含路线信息（距离、耗时、行进步骤）的 JSON 字符串。
    """
    if not origin_address or not destination_address:
        err_msg = "参数错误：origin_address、destination_address不能为空"
        logger.warning(f"[amap_route] {err_msg}")
        return json.dumps({"error": err_msg}, ensure_ascii=False)

    if route_type not in ("walking", "driving", "transit"):
        logger.warning(f"[amap_route] 不支持的route_type={route_type}，回退driving驾车模式")
        route_type = "driving"

    logger.info(f"[amap_route] 规划路线 {origin_address} -> {destination_address}, type={route_type}")

    # 搜索前先查向量缓存：命中直接复用，避免重复调用高德API
    cache_query = f"{origin_address} -> {destination_address} ({route_type})"
    cached = cache_lookup("amap_route", cache_query)
    if cached is not None:
        logger.info(f"[amap_route] 命中路线向量缓存 {origin_address} -> {destination_address}")
        return json.dumps(cached, ensure_ascii=False)

    try:
        service = get_amap_service()
        result = await service.async_plan_route(
            origin_address=origin_address,
            destination_address=destination_address,
            origin_city=origin_city,
            destination_city=destination_city,
            route_type=route_type,
        )
    except Exception as e:
        logger.exception("[amap_route] 调用异常")
        return _error_response(route_type, e)

    if result.get("status") != "1":
        return json.dumps({
            "error": f"高德路线规划失败: {result.get('info', 'unknown')}",
        }, ensure_ascii=False)

    # 有用搜索结果写入向量库，供后续搜索复用
    cache_store("amap_route", cache_query, result, {
        "origin": origin_address,
        "destination": destination_address,
        "route_type": route_type,
    })
    return json.dumps(result, ensure_ascii=False, indent=2)
