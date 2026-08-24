"""Unsplash图片服务
封装 Unsplash 图片 API 调用服务，提供图片搜索、获取单张图片地址；
实现单例模式，全局复用服务实例。"""

import httpx
from typing_extensions import Optional, List, Dict
from ..config import get_settings
from ..utils.retry import async_retry

import logging

# 获取当前模块日志实例
logger = logging.getLogger(__name__)

# Unsplash境外接口国内访问经常超时：请求超时缩短到3秒，失败快速降级（前端有占位图兜底）
UNSPLASH_TIMEOUT_SECONDS: float = 3.0

class UnsplashService:
    """Unsplash图片服务类，封装搜索图片、提取图片链接能力
    内部使用httpx异步客户端，适配FastAPI异步环境，不阻塞事件循环
    """

    def __init__(self):
        """初始化，读取配置，校验access_key合法性"""
        settings = get_settings()
        # 去除配置值两端引号、空格，避免配置文件复制粘贴带多余符号
        self.access_key = settings.unsplash_access_key.strip().strip('"').strip("'")
        self.base_url = "https://api.unsplash.com"
        # 初始化异步http客户端；不在这里close，交由调用方管理生命周期
        self._client: Optional[httpx.AsyncClient] = None

        # 配置合法性校验：启动阶段就发现密钥缺失，不要等到业务请求才报错
        if not self.access_key:
            logger.warning("[UnsplashService] unsplash_access_key 配置为空，图片接口将全部返回空数据")

    @property
    def client(self) -> httpx.AsyncClient:
        """懒加载异步httpx客户端属性，复用同一个连接池"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(UNSPLASH_TIMEOUT_SECONDS))
        return self._client

    @staticmethod
    def _get_fallback_english_query(chinese_name: str) -> Optional[str]:
        """
        根据中文景点名称，匹配兜底Unsplash英文搜索词
        返回None代表没有匹配分类，不做兜底搜索
        """
        name = chinese_name.lower()
        # key关键词列表 -> Unsplash英文搜索词，可继续扩充
        fallback_mapping = [
            # --- 你原有的19组（保留） ---
            (["湖", "泊", "水库"], "lake landscape china"),
            (["海", "海滩", "大海", "滨海"], "sea beach scenery"),
            (["江", "河", "溪流"], "river natural scenery"),
            (["山", "峰", "岭", "秀山"], "mountain landscape china"),
            (["雪山"], "snow mountain scenery"),
            (["峡谷", "沟"], "grand canyon nature"),
            (["瀑布"], "waterfall natural view"),
            (["草原", "草场"], "grassland landscape"),
            (["森林", "雨林", "树林"], "forest natural scenery"),
            (["岛", "海岛"], "island sea view"),
            (["溶洞", "岩洞"], "cave stalactite"),
            (["古镇", "古街", "古城"], "ancient town china"),
            (["博物馆", "博物院"], "chinese museum building"),
            (["寺", "寺庙", "禅院"], "chinese ancient temple"),
            (["塔", "塔楼", "古塔"], "ancient chinese pagoda"),
            (["高楼", "大厦", "摩天"], "modern city high‑rise building"),
            (["古建筑", "古建"], "chinese ancient architecture"),
            (["公园"], "city park landscape"),
            (["广场"], "city public square"),

            # --- 新增水域类 ---
            (["湿地", "沼泽"], "wetland natural reserve"),
            (["池塘", "荷塘"], "pond lotus scenery"),
            (["温泉", "热泉"], "hot spring natural"),
            (["运河"], "canal waterway"),
            (["海湾", "港湾"], "bay sea view"),
            (["海峡"], "strait sea"),
            (["礁石", "珊瑚礁"], "coral reef underwater"),
            (["冰湖", "天池"], "crater lake mountain"),
            (["瀑布群"], "waterfalls cascade"),

            # --- 新增山岳/地貌类 ---
            (["丘陵", "岗"], "hill pastoral landscape"),
            (["高原"], "plateau grassland"),
            (["盆地"], "basin landscape"),
            (["沙漠", "沙丘", "戈壁"], "desert dune landscape"),
            (["雅丹", "风蚀"], "yardang landform china"),
            (["丹霞", "赤壁"], "danxia red rock china"),
            (["喀斯特", "石林", "峰林"], "karst limestone landscape"),
            (["冰川", "冰舌", "冰帽"], "glacier ice scenery"),
            (["火山", "熔岩"], "volcano crater landscape"),
            (["悬崖", "峭壁", "断崖"], "cliff rock face"),
            (["石滩", "砾石"], "rocky beach shore"),
            (["黄土", "塬", "梁"], "loess plateau china"),

            # --- 新增植被/生态类 ---
            (["竹林", "竹海"], "bamboo forest china"),
            (["梯田", "水田"], "rice terraces china"),
            (["茶园", "茶山"], "tea plantation hills"),
            (["果园", "果林"], "orchard fruit trees"),
            (["花海", "花田", "油菜花"], "flower field sea"),
            (["草原", "草甸", "牧场"], "meadow pasture grassland"),  # 细化
            (["红树林"], "mangrove forest"),
            (["针叶林", "松林"], "pine forest landscape"),
            (["落叶林", "秋林"], "autumn forest colorful"),
            (["热带雨林"], "tropical rainforest canopy"),

            # --- 新增气候/天象（作为景观背景） ---
            (["云海", "云雾"], "sea of clouds mountain"),
            (["日出", "朝霞"], "sunrise golden hour"),
            (["日落", "晚霞", "夕阳"], "sunset orange sky"),
            (["彩虹"], "rainbow sky"),
            (["雪景", "雾凇", "冰挂"], "snow winter landscape"),
            (["极光"], "aurora borealis night"),

            # --- 新增人文/建筑补充 ---
            (["宫殿", "皇宫", "王府"], "chinese imperial palace"),
            (["教堂", "礼拜堂"], "church architecture"),
            (["城堡", "古堡"], "castle fortress"),
            (["桥梁", "桥", "拱桥"], "bridge river architecture"),
            (["水乡", "江南"], "water town china"),
            (["石窟", "石刻", "造像"], "buddhist grotto statues"),
            (["陵墓", "皇陵"], "chinese imperial tomb"),
            (["城墙", "城楼"], "ancient city wall china"),
            (["牌坊", "牌楼"], "chinese memorial archway"),
            (["戏台", "戏楼"], "chinese traditional stage"),
            (["书院", "学宫"], "ancient chinese academy"),

            # --- 新增自然保护区和动物主题 ---
            (["自然保护区", "国家公园"], "national park nature"),
            (["候鸟", "湿地鸟类"], "migratory birds wetland"),
            (["野生动物", "兽类"], "wild animals safari"),
            (["蝴蝶", "昆虫"], "butterfly garden"),
            (["花鸟", "鸟类"], "birds in nature"),

            # --- 新增特殊地貌 ---
            (["天坑", "地缝"], "tiankeng sinkhole china"),
            (["天生桥", "拱门"], "natural stone arch"),
            (["海蚀", "风动石"], "coastal erosion rock"),
            (["冰臼", "冰川遗迹"], "glacial pothole relic"),

            # --- 新增城市自然（郊野） ---
            (["郊野公园", "森林公园"], "country park forest"),
            (["植物园"], "botanical garden exotic plants"),
            (["动物园"], "zoo animal enclosure"),

            # --- 补充一些常见字 ---
            (["古道", "驿道"], "ancient road china"),
            (["古桥"], "old stone bridge"),
            (["古村", "古寨"], "ancient village china"),
        ]

        for keyword_list, en_query in fallback_mapping:
            for kw in keyword_list:
                if kw in name:
                    return en_query
        return None

    async def search_photos(self, query: str, per_page: int = 10) -> List[Dict]:
        """
        搜索Unsplash图片；原始搜索无结果自动执行分类兜底搜索
        :param query: 搜索关键词，例如 "xinjiang grassland"
        :param per_page: 返回图片数量，最大受Unsplash接口限制
        :return: 图片结果列表，失败返回空列表
        """
        # 入参校验：关键词为空直接返回，不发起http请求
        query = query.strip()
        if not query:
            logger.debug("[UnsplashService] search_photos query为空，直接返回空列表")
            return []

        # 密钥为空，直接返回，避免无效网络请求
        if not self.access_key:
            return []

        url = f"{self.base_url}/search/photos"
        headers = {"Authorization": f"Client-ID {self.access_key}"}
        params = {"query": query, "per_page": per_page}

        try:
            logger.debug(f"[UnsplashService] 请求搜索图片 query={query}, per_page={per_page}")

            # 履约保障：Unsplash 网络瞬时错误自动重试（指数退避），失败抛异常交给外层回落
            async def _do_search(req_url: str, req_params: dict) -> dict:
                resp_get = await self.client.get(url=req_url, params=req_params, headers=headers)
                # 如果http状态码4xx/5xx直接抛出异常
                resp_get.raise_for_status()
                return resp_get.json()

            resp_json = await async_retry(
                lambda: _do_search(url, params), max_retries=2, base_delay=1.0, max_delay=4.0, label="unsplash"
            )
            result_list = resp_json.get("results", [])

            # ============兜底逻辑：原始搜索没有图片，执行分类搜索============
            if len(result_list) == 0:
                fallback_query = self._get_fallback_english_query(query)
                if fallback_query is not None:
                    logger.info(f"[UnsplashService] 原始搜索无结果，执行兜底搜索，原始:{query} 兜底词:{fallback_query}")
                    fallback_params = {"query": fallback_query, "per_page": per_page}
                    fallback_json = await async_retry(
                        lambda: _do_search(url, fallback_params), max_retries=2, base_delay=1.0, max_delay=4.0, label="unsplash_fallback"
                    )
                    result_list = fallback_json.get("results", [])

            logger.debug(f"[UnsplashService] 搜索完成，最终获取到 {len(result_list)} 张图片")
            return result_list

        except httpx.HTTPStatusError as e:
            # http状态码错误：401密钥错误、403限流、404等
            # 410 Gone：部分Unsplash端点已废弃，仅记录warning，不打印堆栈
            if e.response.status_code == 410:
                logger.warning(f"[UnsplashService] Unsplash接口已废弃 status_code=410, query={query}")
            else:
                logger.warning(f"[UnsplashService] HTTP状态异常 status_code={e.response.status_code}, query={query}")
            return []
        except httpx.TransportError as e:
            # 网络层面异常：超时、连接失败、DNS解析失败（境外接口常见，快速降级，不刷错误堆栈）
            logger.warning(f"[UnsplashService] 网络请求失败 query={query}, error={type(e).__name__}: {str(e)[:120]}")
            return []
        except ValueError as e:
            # json解析失败，返回的不是合法json
            logger.error(f"[UnsplashService] JSON解析失败 query={query}", exc_info=True)
            return []
        except Exception as e:
            # 兜底捕获其他未知异常
            logger.exception(f"[UnsplashService] 未知异常 query={query}")
            return []

    async def get_photo_url(self, query: str) -> Optional[str]:
        """
        获取单张图片访问URL，优先取small，降级取regular
        自动支持分类兜底搜索
        :param query: 搜索关键词
        :return: 图片url字符串；无结果/调用失败返回None
        """
        photos = await self.search_photos(query, per_page=1)
        if not photos:
            return None
        # 优先小图，小图不存在取regular大图
        urls: Dict = photos[0].get("urls", {})
        img_url = urls.get("small") or urls.get("regular")
        logger.debug(f"[UnsplashService] 获取图片url={img_url} query={query}")
        return img_url

# 单例全局实例
_unsplash_service: Optional[UnsplashService] = None


def get_unsplash_service() -> UnsplashService:
    """获取 UnsplashService 单例对象
    注意：在FastAPI生命周期事件中不要直接实例化大量IO资源；服务实例懒加载
    """
    global _unsplash_service
    if _unsplash_service is None:
        logger.info("[UnsplashService] 创建全局单例 UnsplashService")
        _unsplash_service = UnsplashService()
    return _unsplash_service