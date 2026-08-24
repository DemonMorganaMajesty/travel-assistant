"""地图服务API路由
作用：封装高德地图相关 HTTP 接口，对外提供 POI 搜索、天气查询、路线规划，供前端调用，
同时 Agent 内部 MCP 工具也会底层调用amap_service服务层。"""

from fastapi import APIRouter, HTTPException, Query
#from typing import Optional
from ...models.schemas import (
    POISearchRequest,
    POISearchResponse,
    RouteRequest,
    RouteResponse,
    WeatherResponse
)
from ...services.amap_service import get_amap_service
from ...rag.search_cache import cache_lookup, cache_store

import logging

# ----------------------全局日志配置----------------------
logger = logging.getLogger(__name__)

# 参1：这个路由下所有接口的路径都以/map开头
# 参2：在swagger文档中把这些接口归到地图服务分组下
router = APIRouter(prefix="/map", tags=["地图服务"])


@router.get(
    "/poi",
    response_model=POISearchResponse,   # 指定响应体JSON Schema，自动校验+生成文档
    summary="搜索POI",                   # swagger简短标题
    description="根据关键词搜索POI(兴趣点)" # swagger详细描述
)
async def search_poi(
    keywords: str = Query(..., description="搜索关键词", example="故宫"),
    city: str = Query(..., description="城市", example="北京"),
    citylimit: bool = Query(True, description="是否限制在城市范围内")
):
    """
    搜索POI
    
    Args:
        keywords: 搜索关键词
        city: 城市
        citylimit: 是否限制在城市范围内
        
    Returns:
        POI搜索结果
    """
    try:
        logger.info(f"POI搜索请求 keywords={keywords}, city={city}, citylimit={citylimit}")

        # 搜索前先查向量缓存：命中直接复用高德POI搜索结果
        cache_query = f"{keywords} {city}"
        cached = cache_lookup("amap_poi", cache_query)
        if cached is not None and isinstance(cached.get("pois"), list):
            logger.info(f"POI搜索命中向量缓存 keywords={keywords}, city={city}")
            return POISearchResponse(
                success=True,
                message="POI搜索成功（缓存）",
                data=cached["pois"]
            )

        # 获取服务实例
        service = get_amap_service()

        # 调用service层执行业务，路由层不处理具体高德API请求逻辑
        pois = service.search_poi(keywords, city, citylimit)

        # 有用搜索结果写入向量库，供后续搜索复用
        cache_store("amap_poi", cache_query, {"pois": pois}, {"city": city, "keywords": keywords})

        return POISearchResponse(
            success=True,
            message="POI搜索成功",
            data=pois
        )
        
    except Exception as e:
        err_msg = f"POI搜索失败: {str(e)}"
        logger.error(err_msg, exc_info=True)
        print(f"POI搜索失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"POI搜索失败: {str(e)}"
        )


@router.get(
    "/weather",
    response_model=WeatherResponse,
    summary="查询天气",
    description="查询指定城市的天气信息"
)
async def get_weather(
    city: str = Query(..., description="城市名称", example="北京")
):
    """
    查询天气
    
    Args:
        city: 城市名称
        
    Returns:
        天气信息
    """
    try:
        logger.info(f"天气查询请求 city={city}")
        # 获取服务实例
        service = get_amap_service()
        
        # 查询天气
        weather_info = service.get_weather(city)
        
        return WeatherResponse(
            success=True,
            message="天气查询成功",
            data=weather_info
        )
        
    except Exception as e:
        err_msg = f"天气查询失败: {str(e)}"
        logger.error(err_msg, exc_info=True)
        print(f"❌ 天气查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"天气查询失败: {str(e)}"
        )


@router.post(
    "/route",
    response_model=RouteResponse,
    summary="规划路线",
    description="规划两点之间的路线"
)
async def plan_route(request: RouteRequest):
    """
    规划路线

    Args:
        request: 路线规划请求（JSON请求体，对应RouteRequest Pydantic模型）

    Returns:
        路线信息
    """
    try:
        logger.info(
            f"路线规划请求 origin={request.origin_address}, dest={request.destination_address}, type={request.route_type}")
        # 获取服务实例
        service = get_amap_service()
        
        # 规划路线
        route_info = service.plan_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            route_type=request.route_type
        )
        
        return RouteResponse(
            success=True,
            message="路线规划成功",
            data=route_info
        )
        
    except Exception as e:
        err_msg = f"路线规划失败: {str(e)}"
        logger.error(err_msg, exc_info=True)
        print(f"❌ 路线规划失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"路线规划失败: {str(e)}"
        )


@router.get(
    "/health",
    summary="健康检查",
    description="检查地图服务是否正常"
)
async def health_check():
    """地图模块独立健康检查：验证高德服务实例、MCP工具是否加载正常"""
    try:
        # 检查服务是否可用
        service = get_amap_service()
        
        return {
            "status": "healthy",
            "service": "map-service",
            "backend": "amap-rest-api"
        }
    except Exception as e:
        logger.error(f"地图服务健康检查失败 {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"服务不可用: {str(e)}"
        )

