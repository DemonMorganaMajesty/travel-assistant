"""POI相关API路由
提供景点 POI 详情查询、景点图片获取、POI 搜索接口。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx
from ...config import get_settings
from ...services.amap_service import get_amap_service

import logging

# ----------------------全局日志配置----------------------
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/poi", tags=["POI"])


class POIDetailResponse(BaseModel):
    """POI详情响应"""
    success: bool
    message: str
    data: dict | None = None


@router.get(
    "/detail/{poi_id}",
    response_model=POIDetailResponse,
    summary="获取POI详情",
    description="根据POI ID获取详细信息,包括图片"
)
async def get_poi_detail(poi_id: str):
    """
    获取POI详情
    
    Args:
        poi_id: POI ID
        
    Returns:
        POI详情响应
    """
    try:
        logger.info(f"请求POI详情接口，poi_id={poi_id}")
        amap_service = get_amap_service()
        
        # 业务逻辑交给service层，路由层不直接调用高德http接口
        result = amap_service.get_poi_detail(poi_id)
        
        return POIDetailResponse(
            success=True,
            message="获取POI详情成功",
            data=result
        )
        
    except Exception as e:
        err_msg = f"获取POI详情失败: {str(e)}"
        logger.error(err_msg, exc_info=True)
        print(f"❌ 获取POI详情失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取POI详情失败: {str(e)}"
        )



# 常见中国景点 → Unsplash 英文搜索关键词
# 常见中国景点 → Unsplash 英文搜索关键词
_ATTRACTION_EN_MAP = {
    "故宫": "Forbidden City Beijing",
    "长城": "Great Wall of China",
    "八达岭": "Badaling Great Wall",
    "慕田峪": "Mutianyu Great Wall",
    "颐和园": "Summer Palace Beijing",
    "天坛": "Temple of Heaven Beijing",
    "天安门": "Tiananmen Square",
    "鸟巢": "Birds Nest stadium Beijing",
    "水立方": "Water Cube Beijing",
    "兵马俑": "Terracotta Warriors Xian",
    "西湖": "West Lake Hangzhou",
    "雷峰塔": "Leifeng Pagoda Hangzhou",
    "灵隐寺": "Lingyin Temple Hangzhou",
    "外滩": "The Bund Shanghai",
    "东方明珠": "Oriental Pearl Tower Shanghai",
    "豫园": "Yu Garden Shanghai",
    "南京路": "Nanjing Road Shanghai",
    "迪士尼": "Shanghai Disneyland",
    "大熊猫": "Giant Panda Chengdu",
    "宽窄巷子": "Kuanzhai Alley Chengdu",
    "锦里": "Jinli Street Chengdu",
    "武侯祠": "Wuhou Shrine Chengdu",
    "洪崖洞": "Hongyadong Chongqing",
    "磁器口": "Ciqikou Chongqing",
    "解放碑": "Jiefangbei Chongqing",
    "中山陵": "Sun Yatsen Mausoleum Nanjing",
    "夫子庙": "Confucius Temple Nanjing",
    "玄武湖": "Xuanwu Lake Nanjing",
    "滕王阁": "Tengwang Pavilion Nanchang",
    "绳金塔": "Shengjin Pagoda Nanchang",
    "秋水广场": "Qiushui Square Nanchang",
    "八一起义纪念馆": "Nanchang Uprising Memorial",
    "南昌之星摩天轮": "Star of Nanchang Ferris Wheel",

# ========= 笼统通用类别（兜底，不带地名，简洁语义匹配，提升unsplash命中率） =========
    "山": "mountain landscape",
    "高山": "high mountain scenery",
    "峰": "mountain peak landscape",
    "湖": "lake natural scenery",
    "湖泊": "freshwater lake landscape",
    "江河": "river natural scenery",
    "江": "great river landscape",
    "河": "river valley scenery",
    "海": "sea coastal view",
    "古镇": "ancient water town",
    "古街": "old historical street",
    "古城": "ancient historic town",
    "古村": "ancient village countryside",
    "寺庙": "ancient temple",
    "道观": "taoist temple",
    "园林": "classical garden",
    "皇家园林": "imperial garden",
    "瀑布": "waterfall natural scenery",
    "峡谷": "mountain canyon",
    "海岛": "island coastal scenery",
    "沙滩": "tropical beach seaside",
    "溶洞": "karst cave",
    "草原": "grassland prairie scenery",
    "沙漠": "desert dune landscape",
    "戈壁": "gobi desert scenery",
    "雪山": "snow mountain alpine scenery",
    "冰川": "glacier mountain landscape",
    "森林公园": "national forest park",
    "湿地公园": "wetland park nature",
    "城楼": "ancient city gate tower",
    "古塔": "ancient pagoda tower",
    "城墙": "ancient city wall historic",
    "博物馆": "history museum building",
    "纪念馆": "memorial hall building",
    "广场": "large city public square",
    "主题乐园": "theme park amusement",
    "温泉": "hot spring resort",
    "观景台": "mountain viewing platform",
    "栈道": "cliff plank road mountain",
    "竹海": "bamboo forest mountain scenery",
    "森林": "mountain forest nature",
    "梯田": "mountain terrace farmland scenery",
    "渔村": "coastal fishing village",
    "老街": "old pedestrian street market",

    "山谷": "mountain valley landscape",
    "天池": "alpine crater lake mountain",
    "沼泽": "marsh wetland natural scenery",
    "红树林": "mangrove wetland coastal scenery",
    "礁石": "sea rock reef shore",
    "海岸": "seashore coastline scenery",
    "峰林": "karst peak forest landscape",
    "石林": "stone forest karst landscape",
    "天坑": "karst sinkhole geology",
    "地下河": "underground river karst cave",
    "冰洞": "ice cave karst landscape",
    "丹霞": "red rock landform scenery",
    "雅丹": "wind erosion landform gobi",
    "火山": "volcanic landform geopark",
    "草甸": "alpine meadow grassland",
    "海子": "high altitude alpine lake",
    "胡杨林": "populus euphratica desert forest",
    "花海": "wild flower field countryside scenery",
    "茶田": "tea plantation mountain terrace",
    "红叶": "red autumn leaves forest",
    "彩林": "colorful autumn forest mountain",
    "银杏林": "ginkgo ancient forest autumn",
    "雾凇": "rime ice frost winter landscape",
    "云海": "sea of clouds mountain sunrise",
    "日出": "mountain sunrise landscape",
    "日落": "mountain sunset scenic view",
    "星空": "night star sky wilderness",

    "古桥": "ancient stone bridge architecture",
    "廊桥": "covered ancient bridge",
    "浮桥": "traditional floating bridge river",
    "吊桥": "mountain suspension bridge gorge",
    "牌坊": "ancient memorial archway",
    "祠堂": "ancestral hall ancient building",
    "会馆": "ancient commercial guild hall",
    "书院": "ancient academy of learning",
    "古戏台": "traditional ancient opera stage",
    "石窟": "buddhist grotto cave art historic",
    "摩崖石刻": "cliff stone carving ancient",
    "鼓楼": "ancient drum tower town",
    "钟楼": "ancient bell tower historic city",
    "土楼": "round earth building folk architecture",
    "吊脚楼": "stilted folk building village",
    "苗寨": "ethnic ancient mountain village",
    "侗寨": "ethnic mountain countryside village",
    "碉楼": "watchtower fort building village",
    "古渡口": "ancient river ferry dock",
    "古道": "ancient mountain trail",
    "茶马古道": "ancient trade mountain trail",
    "水街": "water street canal ancient town",
    "水乡": "water town canal ancient village",
    "大院": "grand courtyard mansion historic",
    "古民居": "traditional ancient folk residence",
    "玻璃栈道": "glass cliff viewing walkway mountain",
    "灯塔": "coastal lighthouse seashore",
    "码头": "ancient river harbor waterfront",
    "古关隘": "ancient mountain pass fort",
    # 【追加补充兜底】
    "佛寺": "buddhist temple",
    "寺院": "ancient temple complex",
    "古刹": "ancient buddhist temple",
    "夜市": "night market street",
    "步行街": "pedestrian shopping street",
    "老城": "old city historic district",
    "老城区": "historic old town district",
    "海滨": "seaside coastal scenery",
    "滨海": "coastal waterfront view",
    "海湾": "sea bay coastal scenery",
    "半岛": "coastal peninsula landscape",
    "雪山湖泊": "alpine mountain lake scenery",
    "高山草甸": "alpine grassland meadow",
    "古寺庙群": "ancient temple complex",
    "遗址": "ancient ruin historic site",
    "考古遗址": "archaeological ruin site",
    "古堡": "ancient fortress fortification",
    "要塞": "ancient fortress stronghold",
    "游船": "river cruise boat waterfront",
    "码头古镇": "waterfront ancient town harbor",
    "冰雪": "snow ice winter landscape",
    "滑雪场": "ski resort mountain snow",
    "古镇水巷": "canal alley ancient town",
    "农家": "rural farm village countryside",
    "村落": "rural countryside village",
    "观景平台": "scenic viewing platform",
    "雕塑公园": "sculpture public park",
    "城市公园": "urban city public park",
    "滨江": "river waterfront promenade",
    "沿河": "riverside waterfront scenery",
    "文创街区": "creative cultural block street",
    "历史街区": "historical cultural block street",
    "艺术街区": "artistic cultural block street",
    "商业街区": "commercial cultural block street",
    "工业街区": "industrial cultural block street",
    "旅游街区": "tourist cultural block street",
    "美食街区": "cuisine cultural block street",
    "购物街区": "shopping cultural block street",
    "休闲街区": "recreational cultural block street",
    "娱乐街区": "entertainment cultural block street",
    "购物街": "shopping street commercial",
    "休闲街": "recreational street commercial",
    "娱乐街": "entertainment street commercial",
    "美食街": "cuisine street commercial",

}

def _extract_category_en_query(name: str) -> str:
    """从景点名提取笼统类别关键词，返回 Unsplash 英文搜索词（兜底映射）。

    例如「鄱阳湖」→ 提取「湖」→ "lake natural scenery"；
    优先匹配最长的关键词（更具体），如「高山草甸」优先于「山」。
    没有命中任何类别时返回空字符串。
    """
    if not name:
        return ""
    # 按关键词长度降序匹配：命中最具体的类别，避免「湖」被「湖泊」覆盖
    for kw in sorted(_ATTRACTION_EN_MAP.keys(), key=len, reverse=True):
        if kw in name:
            return _ATTRACTION_EN_MAP[kw]
    return ""


@router.get(
    "/amap-photo",
    summary="获取景点图片",
    description="优先高德POI获取图片，Unsplash作为备用，最后走类别兜底映射"
)
async def get_amap_photo(name: str, city: str = "北京"):
    """
    获取景点图片，完整兜底链路：
    1. 高德 POI 图片（普通开发者Key不返回photos，升级企业版Key后命中）
    2. Unsplash：预定义英文关键词 > 中文景点名+城市 > 类别兜底 > 城市地标
    3. 类别兜底映射：从景点名提取类别词（如「鄱阳湖」→「湖」）转英文搜索
    """
    logger.info(f"请求景点图片接口，景点名称={name}，城市={city}")

    # --- 1. 优先高德 POI 图片（企业版Key返回photos；普通Key为空则继续走Unsplash） ---
    try:
        from ...services.amap_service import get_amap_service
        amap = get_amap_service()
        amap_result = await amap.async_search_poi(name, city, citylimit=True)
        for poi in amap_result.get("pois", []) or []:
            photos = poi.get("photos") or []
            if not photos:
                continue
            first_url = (photos[0].get("url") or "").strip()
            if not first_url:
                first_url = (photos[0].get("url_big") or "").strip()
            if first_url:
                logger.info(f"[Photo] 高德POI命中图片 name={name} city={city}")
                return {"success": True, "data": {"name": name, "photo_url": first_url}}
    except Exception as e:
        logger.warning(f"[Photo] 高德POI图片查询异常，继续走Unsplash兜底: {e}")

    # --- 2. Unsplash：预定义英文关键词 > 中文+城市 > 类别兜底 > 城市地标 ---
    from ...services.unsplash_service import get_unsplash_service
    unsplash = get_unsplash_service()

    en_keyword = _ATTRACTION_EN_MAP.get(name, "")
    category_query = _extract_category_en_query(name)
    queries = []
    if en_keyword:
        queries.append(en_keyword)
    queries.append(f"{name} {city}")
    if category_query and category_query != en_keyword:
        queries.append(category_query)
    queries.append(f"{city} China landmark")

    # 循环尝试查询，拿到第一个有效图片url直接返回
    for query in queries:
        url = await unsplash.get_photo_url(query)
        if url:
            logger.info(f"[Photo] Unsplash命中图片 name={name} query={query}")
            return {"success": True, "data": {"name": name, "photo_url": url}}

    logger.warning(f"未匹配到景点图片，name={name},city={city}")
    return {"success": False, "data": None}


def _name_overlaps(query: str, result: str) -> bool:
    """
        工具函数：判断搜索关键词与POI返回名称是否指向同一个地点
        清洗全角/半角括号；支持完全匹配、互相包含匹配（最少2字符避免单字误匹配）
        👉 当前文件定义，但本文件**没有调用**，预留给后续POI业务逻辑使用
        :param query: 用户输入搜索词
        :param result: 高德返回POI名称
        :return: True代表是同一个地点
        """
    if not query or not result:
        return False
    # 清洗括号符号，消除全角半角干扰
    q = query.replace("(", "").replace(")", "").replace("\uff08", "").replace("\uff09", "")
    r = result.replace("(", "").replace(")", "").replace("\uff08", "").replace("\uff09", "")

    # 完全相等
    if q == r:
        return True

    # 互相包含，字符数≥2，防止单字符错误匹配
    if len(q) >= 2 and q in r:
        return True
    if len(r) >= 2 and r in q:
        return True
    return False


@router.get(
    "/search",
    summary="搜索POI",
    description="根据关键词搜索POI"
)
async def search_poi(keywords: str, city: str = "北京"):
    """
    搜索POI

    Args:
        keywords: 搜索关键词
        city: 城市名称

    Returns:
        搜索结果
    """
    # search_poi接口开头示例
    if not keywords.strip():
        logger.warning("POI搜索关键词为空")
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")
    try:
        logger.info(f"POI搜索请求，keywords={keywords}, city={city}")
        amap_service = get_amap_service()
        result = amap_service.search_poi(keywords, city)

        return {
            "success": True,
            "message": "搜索成功",
            "data": result
        }

    except Exception as e:
        err_msg = f"搜索POI失败: {str(e)}"
        logger.error(err_msg, exc_info=True)
        print(f"❌ 搜索POI失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"搜索POI失败: {str(e)}"
        )
