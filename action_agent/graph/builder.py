from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from action_agent.models.state import MeetingDebriefState
from action_agent.graph.nodes import (
    summarize_node,
    extract_actions_node,
    assign_owners_node,
    validate_node,
    dispatch_local_node,
    aggregate_dispatch_node,
)
from action_agent.graph.conditions import route_after_validation


def build_graph(checkpointer=None):
    """
    Compile the Meeting Debrief LangGraph pipeline.

    Topology:
        START → summarize → extract_actions → assign_owners → validate
                                ↑                                  │
                                └── [flagged & attempts < max] ────┤
                                                                   ↓
                                                      dispatch_local → aggregate_dispatch → END
    """
    g = StateGraph(MeetingDebriefState)

    g.add_node("summarize",          summarize_node)
    g.add_node("extract_actions",    extract_actions_node)
    g.add_node("assign_owners",      assign_owners_node)
    g.add_node("validate",           validate_node)
    g.add_node("dispatch_local",     dispatch_local_node)
    g.add_node("aggregate_dispatch", aggregate_dispatch_node)

    g.add_edge(START,             "summarize")
    g.add_edge("summarize",       "extract_actions")
    g.add_edge("extract_actions", "assign_owners")
    g.add_edge("assign_owners",   "validate")

    g.add_conditional_edges(
        "validate",
        route_after_validation,
        ["extract_actions", "dispatch_local"],
    )

    g.add_edge("dispatch_local",    "aggregate_dispatch")
    g.add_edge("aggregate_dispatch", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
