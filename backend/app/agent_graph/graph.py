"""LangGraph StateGraph 定义与编译。
LangGraph 的图组装、节点注册、边、条件路由、编译，整个 Agent 的流程图在这里定义。

START → supervisor
supervisor根据next_worker，跳转到 research / logistics / planning / critic
research/logistics/planning 执行完 → 固定边回到 supervisor
critic执行完做二次判断：
    通过 → END 直接结束
    不通过 → 返回 supervisor 重新调度
优化: Supervisor 对确定性阶段使用直接路由（节省 LLM 调用）。


"""

from typing_extensions import Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI

from .state import AgentState
from .supervisor import create_supervisor_node
from .workers.research import create_research_worker
from .workers.logistics import create_logistics_worker
from .workers.planning import create_planning_worker
from .critic import create_critic_node


def build_trip_planner_graph(
    llm: ChatOpenAI,
    tools: list,
) -> StateGraph:
    """构建并编译行程规划 StateGraph。

    Args:
        llm: 所有节点共享的 ChatOpenAI 实例。
        tools: Worker 共享的 LangChain 工具列表。

    Returns:
        编译好的 LangGraph StateGraph，可直接用于调用。
    """
    #保证 工具为列表
    # 生产环境正确写法，不用assert
    if not isinstance(tools, list):
        raise ValueError("tools必须为list")
    if len(tools) == 0:
        raise ValueError("tools不能为空列表")

    # 创建带 ReAct 循环的节点函数
    # supervisor：总调度节点，决定下一步跑哪个worker
    supervisor_node = create_supervisor_node(llm)
    # research worker：做POI搜索、天气查询等信息搜集，需要调用工具，传入tools
    research_node = create_research_worker(llm, tools)
    # logistics worker：交通、住宿处理，同样需要工具
    logistics_node = create_logistics_worker(llm, tools)
    # planning worker：根据搜集信息生成完整行程JSON，不需要外部工具，只需要llm
    planning_node = create_planning_worker(llm)
    # critic节点：校验planning输出的行程质量，只需要llm
    critic_node = create_critic_node(llm)

    # 实例化状态图，绑定全局状态模型AgentState
    workflow = StateGraph(AgentState)

    # ========== 向图注册全部节点 ==========
    # add_node("节点名字", 节点异步函数)，节点名字就是state中next_worker取值
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("research", research_node)
    workflow.add_node("logistics", logistics_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("critic", critic_node)

    # 入口
    workflow.set_entry_point("supervisor")

    # ========== Supervisor的条件路由函数 ==========
    # 根据state["next_worker"]的值，决定跳转到哪一个节点
    def route_supervisor(state: AgentState):
        decision = state.get("next_worker", "research")
        # 兼容历史遗留字符串 "finish"，新代码统一返回END对象
        if decision == "finish":
            return END
        return decision

    # 添加条件边：从supervisor节点出来，执行route_supervisor，映射返回值到目标节点
    workflow.add_conditional_edges(
        source="supervisor",  # 源节点
        path=route_supervisor,  # 路由函数，接收state，输出跳转标识
        path_map={  # 映射表：路由返回值 → 目标节点名称
            "research": "research",
            "logistics": "logistics",
            "planning": "planning",
            "critic": "critic",
            END: END,
        },
    )

    # ========== Worker执行完成后，固定边：全部回到supervisor调度器 ==========
    # Worker 始终返回 Supervisor
    workflow.add_edge("research", "supervisor")
    workflow.add_edge("logistics", "supervisor")
    workflow.add_edge("planning", "supervisor")

    # ========== Critic审查完毕，条件路由 ==========
    # critic执行结束：
    #  - 裁决为 pass / 强制放行 / next_worker=END → 直接结束图，不再回supervisor，
    #    避免 supervisor 再次调度 critic/planning 形成死循环（递归上限问题）
    #  - 裁决为重做（research/logistics/planning）→ 回supervisor重新调度
    def route_after_critic(state: AgentState):
        fb = (state.get("review_feedback") or "").lower()
        #校验通过 / 达到最大重试次数强制放行 → 返回END 而不是无条件返回supervisor
        if state.get("next_worker") == END or "pass" in fb or "多次生成校验失败" in fb:
            return END
        return "supervisor"

#如果 critic 执行完还无条件边返回 supervisor，supervisor 又会再次调度 critic，
# 出现无限循环，触发 RecursionError 递归超限。解决死循环:
    workflow.add_conditional_edges(
        source="critic",
        path=route_after_critic,
        path_map={
            "supervisor": "supervisor",
            END: END,
        },
    )

    # 检查点：MemorySaver把每一步的state保存内存，支持thread_id会话，支持断点续跑
    memory = MemorySaver()
    compiled_graph = workflow.compile(checkpointer=memory)

    return compiled_graph
