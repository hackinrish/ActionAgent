from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from action_agent.models.state import MeetingDebriefState
from action_agent.graph.nodes import (
    summarize_node,
    extract_actions_node,
    assign_owners_node,
    validate_node,
    dispatch_notion_node,
    dispatch_jira_node,
    dispatch_slack_node,
    aggregate_dispatch_node,
)
from action_agent.graph.conditions import route_after_validation


def build_graph(checkpointer=None):
    """
    Compile the Meeting Debrief LangGraph pipeline.

    Topology (Phase 3):
        START → summarize → extract_actions → assign_owners → validate
                                ↑                                  │
                                └── [flagged & attempts < max] ────┤
                                                                   ↓ Send fan-out
                                          dispatch_notion ─┐
                                          dispatch_jira   ─┼─→ aggregate_dispatch → END
                                          dispatch_slack  ─┘
    """
    g = StateGraph(MeetingDebriefState)

    g.add_node("summarize",           summarize_node)
    g.add_node("extract_actions",     extract_actions_node)
    g.add_node("assign_owners",       assign_owners_node)
    g.add_node("validate",            validate_node)
    g.add_node("dispatch_notion",     dispatch_notion_node)
    g.add_node("dispatch_jira",       dispatch_jira_node)
    g.add_node("dispatch_slack",      dispatch_slack_node)
    g.add_node("aggregate_dispatch",  aggregate_dispatch_node)

    g.add_edge(START,             "summarize")
    g.add_edge("summarize",       "extract_actions")
    g.add_edge("extract_actions", "assign_owners")
    g.add_edge("assign_owners",   "validate")

    # route_after_validation returns either "extract_actions" (str) or list[Send]
    g.add_conditional_edges(
        "validate",
        route_after_validation,
        ["extract_actions", "dispatch_notion", "dispatch_jira", "dispatch_slack"],
    )

    # All parallel dispatch nodes join at aggregate_dispatch
    g.add_edge("dispatch_notion",    "aggregate_dispatch")
    g.add_edge("dispatch_jira",      "aggregate_dispatch")
    g.add_edge("dispatch_slack",     "aggregate_dispatch")
    g.add_edge("aggregate_dispatch", END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
