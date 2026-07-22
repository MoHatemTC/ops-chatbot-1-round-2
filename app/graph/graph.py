"""Phase 1 graph orchestration for retrieve -> answer -> router -> escalate."""

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, StateGraph

from app.core.metrics import session_ticket_links_total
from app.core.observability import append_langfuse_tags
from app.graph.nodes.answer import grounded_answer
from app.graph.nodes.router import route_after_router, router_node
from app.graph.state import SessionGraphState
from app.services.escalation import trigger_answering_escalation


async def retrieve_node(
    state: SessionGraphState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Minimal retrieve node for Phase 1 orchestration.

    This does not replace the retrieval subsystem. It marks that retrieval-phase
    preprocessing has occurred and preserves the graph shape required by the task.
    """
    if config:
        metadata = config.get("metadata")
        if isinstance(metadata, dict):
            append_langfuse_tags(metadata, "phase1-routing", "node:retrieve")

    return {
        "retrieved": True,
    }


async def answer_node(
    state: SessionGraphState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Run the grounded answer node and project its escalation signal into graph state."""
    if config:
        metadata = config.get("metadata")
        if isinstance(metadata, dict):
            append_langfuse_tags(metadata, "phase1-routing", "node:answer")

    result = await grounded_answer(state, config)

    answer_signal = False
    answer_reason = None

    messages = result.get("messages", [])
    if messages:
        latest = messages[-1]
        if isinstance(latest, AIMessage):
            grounding = latest.additional_kwargs.get("grounding", {})
            answer_signal = bool(grounding.get("needs_escalation", False))
            answer_reason = grounding.get("escalation_reason")

    return {
        "messages": messages,
        "answer_generated": True,
        "answer_escalation_signal": answer_signal,
        "answer_escalation_reason": answer_reason,
        "failed_turn_count": state.failed_turn_count + (1 if answer_signal else 0),
    }


async def escalate_node(
    state: SessionGraphState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Trigger the shared escalation contract and store the returned ticket link."""
    if state.escalation_context is None:
        return {}

    if config:
        metadata = config.get("metadata")
        if isinstance(metadata, dict):
            append_langfuse_tags(
                metadata,
                "phase1-routing",
                "node:escalate",
                f"reason:{state.escalation_context.trigger_reason}",
            )

    result = await trigger_answering_escalation(
        reason=state.escalation_context.trigger_reason,
        problem=state.escalation_context.problem,
        what_was_tried=state.escalation_context.what_was_tried,
        context=state.escalation_context.context,
        suggested_next_step=state.escalation_context.suggested_next_step,
        summary=state.escalation_context.summary,
        user_goal=state.escalation_context.user_goal,
        key_facts=state.escalation_context.key_facts,
        assistant_actions=state.escalation_context.assistant_actions,
        open_questions=state.escalation_context.open_questions,
        session_id=state.session_id,
        user_id=state.user_id,
    )

    session_ticket_links_total.labels(status="linked" if result.ticket_id else "missing_ticket_id").inc()

    return {
        "ticket_id": result.ticket_id,
        "route_decision": "escalate",
    }


def build_phase1_graph(*, checkpointer: Any | None = None):
    """Build the Week 2 Phase 1 orchestration graph."""
    graph = StateGraph(SessionGraphState)

    graph.add_node("retrieve", retrieve_node)
    graph.add_node("answer", answer_node)
    graph.add_node("router", router_node)
    graph.add_node("escalate", escalate_node)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", "router")
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {
            "escalate": "escalate",
            "end": END,
        },
    )
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer)
