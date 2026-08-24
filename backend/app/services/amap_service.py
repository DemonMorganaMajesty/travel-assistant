"""高德地图服务封装 - 从 MCP 迁移到 httpx。
把高德地图 REST API 做 Python 封装，替换原来 MCP 工具调用，直接使用httpx发 HTTP 请求。
提供能力：POI 搜索、天气查询、路线规划、地址转坐标、POI 详情查询；实现单例模式，全局复用同一个服务实例。
依赖：httpx做 http 客户端；读取项目配置get_settings()拿高德api_key。
"""

import asyncio
import json
import os
import re
from typing_extensions import List, Dict, Any, Optional
import httpx
from ..config import get_settings
from ..utils.retry import async_retry

import logging
# 获取模块日志，统一使用项目logger，不要print
logger = logging.getLogger(__name__)

# 高德方向接口只接受 "经度,纬度" 坐标，地址文本需要先调用地理编码转成坐标
_COORD_PATTERN = re.compile(r"^\d+(\.\d+)?,\d+(\.\d+)?$")
_AMAP_REQUEST_SEMAPHORE = asyncio.Semaphore(2)
_AMAP_QUOTA_INFO = "CUQPS"


def _is_coordinate(text: str) -> bool:
    """判断地址是否已经是高德坐标格式（lng,lat）。"""
    return bool(_COORD_PATTERN.match((text or "").strip()))


def _geo_city(geo: dict) -> str:
    """从地理编码结果中安全提取城市名（高德 city 字段可能是字符串或列表）。"""
    city = geo.get("city") or ""
    if isinstance(city, list):
        return str(city[0]) if city else ""
    return str(city)


class AmapService:
    """高德地图 API 服务封装，使用直接 HTTP 调用。
    注意：FastAPI项目优先使用async_*异步方法；普通脚本可以使用同步方法
    """
    BASE_URL = "https://restapi.amap.com/v3"

    def __init__(self):
        """构造函数：读取配置拿到高德密钥；初始化同步httpx客户端"""
        settings = get_settings()
        self.api_key = settings.amap_api_key
        #复用httpx Client，复用tcp连接，减少握手开销，不要每次请求新建
        self._sync_client = httpx.Client(timeout=15.0)

    def _sync_request(self, endpoint: str, params: dict) -> dict:
        """【同步内部请求】使用复用的同步客户端发起GET请求。
        供 search_poi / get_weather / plan_route 等同步方法使用；
        不要在FastAPI异步函数里调用，会阻塞事件循环，异步场景请使用 _request。
        :param endpoint: api接口路径，例如 place/text
        :param params: 请求查询参数
        :return: 高德接口原始返回dict，业务失败status=0
        """
        params["key"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            resp = self._sync_client.get(url, params=params)
            resp.raise_for_status()  # http状态码非2xx抛异常
            resp_json = resp.json()
            logger.debug(f"[AmapSync] endpoint={endpoint}, params={params}, status={resp_json.get('status')}")
            if resp_json.get("status") == "0":
                logger.warning(f"[AmapSync] 高德业务失败 endpoint={endpoint}, info={resp_json.get('info')}")
                # 致命Key配置错误：明确提示用户检查Key平台类型，避免误以为是网络问题
                _warn_fatal_amap_error(endpoint, resp_json.get("info", ""))
                _warn_quota_amap_error(endpoint, resp_json.get("info", ""))
            return resp_json
        except httpx.HTTPStatusError as e:
            logger.error(f"[AmapSync] HTTP状态异常 {endpoint}, code={e.response.status_code}, err={str(e)}")
            return {"status": "0", "info": f"http_status_error:{str(e)}"}
        except httpx.TimeoutException:
            logger.error(f"[AmapSync] 请求超时 endpoint={endpoint}")
            return {"status": "0", "info": "request timeout"}
        except Exception as e:
            logger.exception(f"[AmapSync] 未知异常 endpoint={endpoint}")
            return {"status": "0", "info": str(e)}

    async def _request(self, endpoint: str, params: dict) -> dict:
        """【异步内部请求】适配FastAPI异步路由/agent异步节点，不会阻塞事件循环
        :param endpoint: api接口路径，例如 place/text
        :param params: 请求查询参数
        :return: 高德接口原始返回dict，业务失败status=0
        """
        params["key"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}"

        async def _do_get() -> dict:
            """内部闭包：单次HTTP请求，异常向上抛给 async_retry 做指数退避重试。"""
            # 使用异步Client上下文管理器
            async with _AMAP_REQUEST_SEMAPHORE:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()  # http状态码非2xx抛异常
                    resp_json = resp.json()
                    logger.debug(f"[AmapAsync] endpoint={endpoint}, params={params}, status={resp_json.get('status')}")
                    return resp_json

        try:
            # 履约保障：网络超时/连接异常这类瞬时错误自动重试（指数退避，最多3次尝试）
            # 业务失败（status=0，如Key错误/参数错误）不作为异常抛出，不会重试
            resp_json = await async_retry(_do_get, max_retries=2, base_delay=1.0, max_delay=4.0, label=f"amap:{endpoint}")
            if resp_json is None:
                return {"status": "0", "info": "请求失败（重试后仍失败）"}
            # CUQPS 是高德返回的业务级 QPS 限流，不会抛 HTTP 异常；等待后只补偿重试一次。
            if resp_json.get("status") == "0" and _AMAP_QUOTA_INFO in str(resp_json.get("info", "")):
                logger.warning("[AmapAsync] CUQPS 限流 endpoint=%s，等待 2 秒后重试一次", endpoint)
                await asyncio.sleep(2.0)
                resp_json = await _do_get()
            # 打印高德业务返回信息，方便排错
            if resp_json.get("status") == "0":
                logger.warning(f"[AmapAsync] 高德业务失败 endpoint={endpoint}, info={resp_json.get('info')}")
                # 致命Key配置错误：明确提示用户检查Key平台类型，避免误以为是网络问题
                _warn_fatal_amap_error(endpoint, resp_json.get("info", ""))
                _warn_quota_amap_error(endpoint, resp_json.get("info", ""))
            return resp_json
        except httpx.HTTPStatusError as e:
            logger.error(f"[AmapAsync] HTTP状态异常 {endpoint}, code={e.response.status_code}, err={str(e)}")
            return {"status": "0", "info": f"http_status_error:{str(e)}"}
        except httpx.TimeoutException:
            logger.error(f"[AmapAsync] 请求超时 endpoint={endpoint}")
            return {"status": "0", "info": "request timeout"}
        except Exception as e:
            logger.exception(f"[AmapAsync] 未知异常 endpoint={endpoint}")
            return {"status": "0", "info": str(e)}

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list:
        """【同步内部请求】向高德地图 API 发起同步GET请求。
        不要在FastAPI异步函数里面调用，会阻塞uvicorn事件循环！请使用上面 _async_request
        :param endpoint: 接口子路径
        :param params: get查询参数字典
        :return: dict，高德原始响应，出错返回 status:"0"
        """
        result = self._sync_request("place/text", {
            "keywords": keywords,
            "city": city,
            "citylimit": str(citylimit).lower(),  # 高德要求参数为"true"/"false"字符串
            "offset": 10,  # 每页返回条数
        })
        pois = result.get("pois", [])
        logger.info(f"[AmapSync] search_poi keywords={keywords}, city={city}, result_count={len(pois)}")
        return pois

    async def async_search_poi(self, keywords: str, city: str, citylimit: bool = True) -> dict:
        """【异步】POI搜索，供LangGraph异步Agent工具调用，不阻塞事件循环。
        :return: 高德原始响应dict（status=1成功，pois为结果列表）
        """
        result = await self._request("place/text", {
            "keywords": keywords,
            "city": city,
            "citylimit": str(citylimit).lower(),
            "offset": 10,
        })
        logger.info(f"[AmapAsync] search_poi keywords={keywords}, city={city}, result_count={len(result.get('pois', []))}")
        return result

    def get_weather(self, city: str) -> list:
        """【同步】获取城市天气预报；extensions=all返回未来4天预报
        :param city: 城市名称/城市adcode
        :return: forecasts预报数组；出错返回空列表
        """
        result = self._sync_request("weather/weatherInfo", {
            "city": city,
            "extensions": "all",
        })
        forecasts = result.get("forecasts", [])
        logger.info(f"[AmapSync] get_weather city={city}, forecasts_len={len(forecasts)}")
        return forecasts

    async def async_get_weather(self, city: str) -> dict:
        """【异步】获取天气预报，供LangGraph异步Agent工具调用。
        :return: 高德原始响应dict（status=1成功，forecasts为预报列表）
        """
        result = await self._request("weather/weatherInfo", {
            "city": city,
            "extensions": "all",
        })
        logger.info(f"[AmapAsync] get_weather city={city}, forecasts_len={len(result.get('forecasts', []))}")
        return result


    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict:
        """【同步】规划两点之间路线：步行/驾车/公共交通
        :param origin_address: 起点地址
        :param destination_address: 终点地址
        :param origin_city: 起点城市
        :param destination_city: 终点城市（跨城市路线需要）
        :param route_type: walking / driving / transit
        :return: 高德原始路线dict
        """
        endpoint_map = {
            "walking": "direction/walking",
            "driving": "direction/driving",
            "transit": "direction/transit/integrated",
        }
        endpoint = endpoint_map.get(route_type, "direction/walking")

        # 高德方向接口只接受 "经度,纬度" 坐标，地址文本先自动地理编码成坐标，避免 INVALID_PARAMS
        origin = origin_address
        destination = destination_address
        if not _is_coordinate(origin):
            geo = self.geocode(origin_address, origin_city)
            if geo and geo.get("location"):
                origin = geo["location"]
                if not origin_city:
                    origin_city = _geo_city(geo)
            else:
                logger.warning(f"[AmapSync] 起点地址无法解析为坐标 origin={origin_address}")
                return {"status": "0", "info": f"起点地址无法解析为坐标: {origin_address}"}
        if not _is_coordinate(destination):
            geo = self.geocode(destination_address, destination_city)
            if geo and geo.get("location"):
                destination = geo["location"]
                if not destination_city:
                    destination_city = _geo_city(geo)
            else:
                logger.warning(f"[AmapSync] 终点地址无法解析为坐标 destination={destination_address}")
                return {"status": "0", "info": f"终点地址无法解析为坐标: {destination_address}"}

        params = {
            "origin": origin,
            "destination": destination,
        }
        # 起点城市参数 key=city
        if origin_city:
            params["city"] = origin_city
        # 终点城市参数 key=cityd，高德接口特殊参数名！跨城才填
        if destination_city:
            params["cityd"] = destination_city

        result = self._sync_request(endpoint, params)
        logger.debug(f"[AmapSync] plan_route route_type={route_type}")
        return result

    async def async_plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict:
        """【异步】规划两点之间路线，供LangGraph异步Agent工具调用。"""
        endpoint_map = {
            "walking": "direction/walking",
            "driving": "direction/driving",
            "transit": "direction/transit/integrated",
        }
        endpoint = endpoint_map.get(route_type, "direction/walking")
        # 高德方向接口只接受 "经度,纬度" 坐标，地址文本先自动地理编码成坐标，避免 INVALID_PARAMS
        origin = origin_address
        destination = destination_address
        if not _is_coordinate(origin):
            geo = await self.async_geocode(origin_address, origin_city)
            if geo and geo.get("location"):
                origin = geo["location"]
                if not origin_city:
                    origin_city = _geo_city(geo)
            else:
                logger.warning(f"[AmapAsync] 起点地址无法解析为坐标 origin={origin_address}")
                return {"status": "0", "info": f"起点地址无法解析为坐标: {origin_address}"}
        if not _is_coordinate(destination):
            geo = await self.async_geocode(destination_address, destination_city)
            if geo and geo.get("location"):
                destination = geo["location"]
                if not destination_city:
                    destination_city = _geo_city(geo)
            else:
                logger.warning(f"[AmapAsync] 终点地址无法解析为坐标 destination={destination_address}")
                return {"status": "0", "info": f"终点地址无法解析为坐标: {destination_address}"}

        params = {
            "origin": origin,
            "destination": destination,
        }
        if origin_city:
            params["city"] = origin_city
        if destination_city:
            params["cityd"] = destination_city
        result = await self._request(endpoint, params)
        logger.debug(f"[AmapAsync] plan_route route_type={route_type}")
        return result

    def geocode(self, address: str, city: Optional[str] = None) -> Optional[dict]:
        """【同步】将中文地址地理编码转换成经纬度坐标（地理编码）
        :param address: 完整地址文本
        :param city: 城市，提升解析准确率
        :return: 解析成功返回geocode字典；失败返回None
        """
        params = {"address": address}
        if city:
            params["city"] = city

        result = self._sync_request("geocode/geo", params)
        geocodes = result.get("geocodes", [])
        if geocodes:
            return geocodes[0]
        logger.warning(f"[AmapSync] geocode 解析失败 address={address},city={city}")
        return None

    async def async_geocode(self, address: str, city: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """【异步】地址转经纬度，异步业务优先"""
        params = {"address": address}
        if city:
            params["city"] = city
        result = await self._request("geocode/geo", params)
        geocodes = result.get("geocodes", [])
        if geocodes:
            return geocodes[0]
        logger.warning(f"[AmapAsync] geocode 解析失败 address={address},city={city}")
        return None

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """【同步】通过poi_id获取POI完整详情（开放时间、介绍、联系方式）
        :param poi_id: 高德返回的poi唯一id
        :return: 原始接口dict
        """
        result = self._sync_request("place/detail", {"id": poi_id})
        logger.debug(f"[AmapSync] get_poi_detail poi_id={poi_id}")
        return result

    async def async_get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """【异步】获取POI详情，异步节点优先"""
        result = await self._request("place/detail", {"id": poi_id})
        logger.debug(f"[AmapAsync] get_poi_detail poi_id={poi_id}")
        return result



# 全局单例变量，整个应用只实例化一次AmapService
_amap_service: Optional[AmapService] = None


def get_amap_service() -> AmapService:
    """获取 AmapService 单例。
    整个项目复用同一个实例，避免重复初始化、重复创建http连接
    使用方式：service = get_amap_service()
    """
    global _amap_service
    if _amap_service is None:
        _amap_service = AmapService()
    return _amap_service

def _warn_quota_amap_error(endpoint: str, info: str) -> None:
    """高德 QPS 配额超限提示：建议降低并发请求频率或稍后重试。"""
    if not info:
        return
    if _AMAP_QUOTA_INFO in info:
        logger.warning(
            f"[Amap] 高德接口 {endpoint} 触发 CUQPS 调用配额超限（QPS超限）。"
            "已通过搜索缓存与重试机制缓解，若频繁出现请降低并发或联系高德提高配额。"
        )


# 高德致命Key错误码：重试无意义，提示用户检查配置
_FATAL_AMAP_ERROR_CODES = ("USERKEY_PLAT_NOMATCH", "INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH_OR_NOT_AUTHORIZED")


def _warn_fatal_amap_error(endpoint: str, info: str) -> None:
    """高德返回致命Key错误时给出明确中文提示，方便用户排查配置。

    USERKEY_PLAT_NOMATCH：Key平台类型与请求平台不匹配（例如Web服务Key被用于JS/小程序平台）。
    """
    if not info:
        return
    if info in _FATAL_AMAP_ERROR_CODES:
        logger.error(
            f"[Amap] 高德Key配置错误 endpoint={endpoint}, info={info}。"
            "请检查高德开放平台控制台的Key类型：POI/天气/路线接口需要使用『Web服务』类型的Key，"
            "当前Key的平台类型与请求平台不匹配，重试无法解决。"
        )


# 全局单例服务实例
_service_instance: Optional["AmapService"] = None
