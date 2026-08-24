"""路线优化工具：用 OR-Tools 求解 TSP（一日内多景点最优顺序）。

封装保持浅层：只做「给定景点经纬度，求总移动距离最短的游览顺序」，
不涉及时间窗、容量等复杂约束，避免过度设计。
依赖 ortools（可选）：未安装时自动回退贪心最近邻算法，功能不受影响。

给定单日一批景点经纬度，求解总移动距离最短游览顺序（TSP 旅行商问题）

"""

import json
import logging
import math
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# OR-Tools 可选依赖：未安装时用贪心算法兜底
try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    _ORTOOLS_AVAILABLE = True
except ImportError:
    _ORTOOLS_AVAILABLE = False
    logger.info("[route_optimizer] 未安装 ortools，自动使用贪心最近邻算法")

# 步行估速 km/h，用于把总距离换算为预计移动时间
WALK_SPEED_KMH = 4.5


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点间球面距离（公里）。 哈弗辛公式"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _solve_tsp_greedy(coords: list) -> list:
    """贪心最近邻：从第0个点出发，每次选择最近的未访问点。 哈弗辛公式
    速度极快 O (n²)，任何数量景点都秒算；
    得到局部最优，不一定全局最优；景点数量少时效果够用；
"""
    n = len(coords)
    visited = [False] * n
    order = [0]
    visited[0] = True
    for _ in range(n - 1):
        cur = order[-1]
        best_d, best_i = None, None
        for j in range(n):
            if not visited[j]:
                d = _haversine_km(*(coords[cur]), *(coords[j]))
                if best_d is None or d < best_d:
                    best_d, best_i = d, j
        order.append(best_i)
        visited[best_i] = True
    return order


def _solve_tsp_ortools(coords: list) -> list:
    """OR-Tools TSP：最小化总行驶距离（标准 API 用法，浅封装）。
    n 个点，从起点出发遍历全部点，最小总路程。

    """
    n = len(coords)
    #下标转换器。
    #Node：业务节点下标，0～n‑1，就是我们的景点编号。
    #Index：Routing内部的索引，Solver使用和Node不一样必须靠manager互相转换。
    #起点固定是 node=0，不能自由指定起点；终点没有强制回到起点
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    
    #创建路由求解模型实例，所有约束、代价、求解都在这个对象操作。
    routing = pywrapcp.RoutingModel(manager)

#from_index / to_index：Routing 内部 Index，不是景点编号！
    def distance_callback(from_index, to_index):
        #把内部 Index 转回业务景点Node下标 i,j。
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        #统一景点
        if i == j:
            return 0
        return int(round(_haversine_km(*(coords[i]), *(coords[j])) * 1000))

    #把距离回调注册进 routing 模型，拿到回调 ID。
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    #把这个距离代价设置给所有车辆，模型优化目标 = 最小总距离
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    #拿一套默认求解参数。
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    #生成初始可行解的策略  每次选代价最小的边构建一条初始路线。
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    #调用c++ 库里的
    #成功：solution 不为 None，保存最优解信息。失败（无解、超时）：solution is None。
    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        logger.warning("[route_optimizer] OR-Tools 无解，回退贪心算法")
        return _solve_tsp_greedy(coords)
    order = []
    #起点内部 index。
    index = routing.Start(0)
    #求解结果中，当前索引点不是最后的 索引
    while not routing.IsEnd(index):
        #把内部 index 转回业务景点 node 编号，append 进 order。
        order.append(manager.IndexToNode(index))
        #取出下一个点的内部 index。
        index = solution.Value(routing.NextVar(index))
    #添加最后一个
    order.append(manager.IndexToNode(index))
    return order


#对外工具入口  被agent 调用
@tool
def optimize_day_route(points_json: str) -> str:
    """优化一天内多个景点的游览顺序，使总移动距离最短（TSP）。

    Args:
        points_json: JSON数组，元素为 {"name": "景点名", "longitude": 116.39, "latitude": 39.91}。

    Returns:
        推荐游览顺序 JSON：{"order": [...], "total_distance_km": 12.5, "estimated_minutes": 167, "engine": "ortools"|"greedy"}。
    """
    try:
        points = json.loads(points_json)
    except Exception as e:
        return json.dumps({"error": f"points_json解析失败: {e}"}, ensure_ascii=False)
    if not isinstance(points, list) or len(points) < 2:
        return json.dumps({"error": "至少需要2个景点坐标"}, ensure_ascii=False)

    coords, names = [], []
    for p in points:
        lng, lat = p.get("longitude"), p.get("latitude")
        if lng is None or lat is None:
            return json.dumps({"error": f"景点缺少坐标: {p.get('name', 'unknown')}"}, ensure_ascii=False)
        coords.append((float(lng), float(lat)))
        names.append(str(p.get("name", "")))

    #选择哪种方式
    if _ORTOOLS_AVAILABLE:
        order = _solve_tsp_ortools(coords)
        engine = "ortools"
    else:
        order = _solve_tsp_greedy(coords)
        engine = "greedy"

    # 累加计算整条路线总距离；
    total_km = 0.0
    for i in range(len(order) - 1):
        total_km += _haversine_km(*(coords[order[i]]), *(coords[order[i + 1]]))
    #按步行速度换算预估分钟。
    minutes = int(round(total_km / WALK_SPEED_KMH * 60))

    #返回 json 字符串：游览景点名称顺序、总距离、预估步行耗时、使用的求解引擎。
    return json.dumps({
        "order": [names[i] for i in order],
        "total_distance_km": round(total_km, 2),
        "estimated_minutes": minutes,
        "engine": engine,
    }, ensure_ascii=False)
