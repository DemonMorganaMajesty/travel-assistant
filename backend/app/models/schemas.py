"""数据模型定义
文件作用：Pydantic 数据模型层，定义所有接口的请求体、响应体结构体；
做参数校验、自动生成 OpenAPI 接口文档、数据序列化 / 反序列化。
FastAPI 项目标准分层：API 路由接收 json → Pydantic 模型解析校验 →
业务层 → Pydantic 模型输出返回 json。
"""

from typing_extensions import List, Optional, Union
from pydantic import BaseModel, Field, field_validator
from datetime import date


# ============ 请求模型 ============
# 请求模型：对应前端post请求的JSON body，用于校验入参

class CityItem(BaseModel):
    """多城市子项：单个城市+用户自定义停留天数
    用于多城市旅行规划，每个城市配置希望游玩的天数
    """
    city_name: str = Field(..., description="城市名称", example="南宁")
    stay_days: int = Field(..., ge=1, le=15, description="该城市计划停留天数", example=2)


class TripRequest(BaseModel):
    """旅行规划请求
    兼容模式：可传入旧字段city做单城市；传入city_list则启用多城市规划
    """
    city: str = Field(..., description="目的地城市（单城市模式使用，多城市请使用city_list）", example="北京")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", example="2027-06-01")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", example="2027-06-03")
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, example=3)
    transportation: str = Field(..., description="交通方式", example="公共交通")
    accommodation: str = Field(..., description="住宿偏好", example="经济型酒店")
    preferences: List[str] = Field(default=[], description="旅行偏好标签", example=["历史文化", "美食"])
    free_text_input: Optional[str] = Field(default="", description="额外要求", example="希望多安排一些博物馆")
    origin: Optional[str] = Field(default="", description="出发地点（不为空）", example="上海")
    adults: Optional[int] = Field(default=1, ge=1, le=50, description="成人人数(>=1)", example=2)
    children: Optional[int] = Field(default=0, ge=0, le=50, description="儿童人数(>=0)，有儿童时规划会考虑儿童友好路线与景点", example=1)
    plan_type: Optional[str] = Field(
        default="",
        description="方案类型：plan_1/plan_2/plan_3；空值则默认方案一",
        example="plan_1"
    )
    plan_count: int = Field(
        default=3, ge=1, le=3,
        description="生成方案数量（1-3个），默认3个",
        example=3
    )
    city_list: Optional[List[CityItem]] = Field(
        default=None,
        description="多城市列表，每个城市配置停留天数；传入该字段则优先启用多城市模式",
        example=[{"city_name": "南宁", "stay_days": 2}, {"city_name": "桂林", "stay_days": 3}]
    )

    class Config:
        """Pydantic模型配置类
             json_schema_extra：给OpenAPI/Swagger文档提供完整请求样例，接口文档页面会直接展示这个示例JSON
             """
        json_schema_extra = {
            "example": {
                "city": "北京",
                "start_date": "2027-06-01",
                "end_date": "2027-06-03",
                "travel_days": 3,
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "preferences": ["历史文化", "美食"],
                "free_text_input": "希望多安排一些博物馆",
                "origin": "上海",
                "adults": 2,
                "children": 1,
                "plan_type": "plan_1",
                "plan_count": 3,
                "city_list": None
            }
        }


class POISearchRequest(BaseModel):
    """ POI = Point of Interest，兴趣点  地图 / 导航领域的专业术语。
    地图上一个有名字、有地址、有经纬度的地点，就叫一条 POI。
    POI搜索请求
       用途：调用高德POI地点搜索接口的入参模型
       """
    keywords: str = Field(..., description="搜索关键词", example="故宫")
    city: str = Field(..., description="城市", example="北京")
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """路线规划请求
        用途：请求两点之间导航路线的入参 """
    origin_address: str = Field(..., description="起点地址", example="北京市朝阳区阜通东大街6号")
    destination_address: str = Field(..., description="终点地址", example="北京市海淀区上地十街10号")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")


# ============ 响应模型 ============
# 响应模型：后端返回给前端的JSON结构体，业务产出数据的结构化定义

class Location(BaseModel):
    """地理位置
       复用模型：景点、酒店、POI都会嵌套这个经纬度对象
       """
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    """景点信息
    DayPlan会嵌套多个Attraction对象；描述单个景点全部属性
    """
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    ticket_price: int = Field(default=0, description="门票价格(元)")


class Meal(BaseModel):
    """餐饮信息，单日行程里面的一餐"""
    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")


class DayPlan(BaseModel):
    """单日行程
    city_name：标记该日程归属哪一座城市；多城市模式生效，用于区分城市与前端地图点位渲染
    """
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    city_name: str = Field(..., description="本天行程所属城市名称，单/多城市都必须填充", example="南宁")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default=[], description="景点列表")
    meals: List[Meal] = Field(default=[], description="餐饮列表")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    # 在类型转换之前执行校验函数(输入温度 22C(str) 检验函数就是先掉单位, 转为int22)
    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod  # 类方法
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位"""
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """旅行计划
    兼容模式：city为单城市使用；city_list不为空代表多城市行程；DayPlan内city_name标记每日所属城市
    """
    city: str = Field(..., description="目的地城市（单城市模式）", example="北京")
    city_list: Optional[List[CityItem]] = Field(default=None,
                                                description="多城市列表，每个城市配置停留天数，多城市模式返回",
                                                example=[{"city_name": "南宁", "stay_days": 2}])
    origin: Optional[str] = Field(default="", description="出发地点（返程回到该地点）", example="上海")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(default="", description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应外层包装模型
        FastAPI标准格式：success标记成功失败，message提示文字，data承载业务主体TripPlan；
        plans 为多方案列表（方案一/方案二/方案三），前端可选择展示；active_plan_type 标记当前选中方案。
        """
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据（兼容单方案）")
    plans: Optional[List[dict]] = Field(default=None, description="多方案列表（按 plan_type 区分）")
    active_plan_type: Optional[str] = Field(default=None, description="当前选中的方案类型")


class POIInfo(BaseModel):
    """POI信息"""
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(default="walking", description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


# ============ 错误响应 ============

class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")
