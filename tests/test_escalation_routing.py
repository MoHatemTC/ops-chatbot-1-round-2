"""Deterministic tests for Phase 1 escalation routing."""

import asyncio

from langchain_core.messages import AIMessage

from app.graph.graph import answer_node, build_phase1_graph, escalate_node
from app.graph.nodes.router import route_turn, router_node
from app.graph.state import EscalationContext, SessionGraphState


def make_state(message: str) -> SessionGraphState:
    return SessionGraphState(
        messages=[{"role": "user", "content": message}],
        session_id="session_123",
        user_id="user_456",
    )


def test_router_does_not_escalate_normal_turn():
    state = make_state("When is the workshop?")
    updated = router_node(state)

    assert updated["escalation_needed"] is False
    assert updated["route_decision"] == "end"
    assert route_turn(state) == "end"


def test_router_escalates_on_explicit_human_request():
    state = make_state("I want a human to help me.")
    updated = router_node(state)

    assert updated["escalation_needed"] is True
    assert updated["explicit_human_requested"] is True
    assert updated["route_decision"] == "escalate"


def test_router_escalates_on_fuzzy_human_request_typo():
    state = make_state("Please, I want a humna to help me.")
    updated = router_node(state)

    assert updated["escalation_needed"] is True
    assert updated["explicit_human_requested"] is True
    assert updated["route_decision"] == "escalate"


def test_router_escalates_on_frustration():
    state = make_state("This is frustrating and you are not helping.")
    updated = router_node(state)

    assert updated["escalation_needed"] is True
    assert updated["frustration_detected"] is True
    assert updated["route_decision"] == "escalate"


def test_router_escalates_on_fuzzy_frustration_typo():
    state = make_state("This is frustratng and you are not helping.")
    updated = router_node(state)

    assert updated["escalation_needed"] is True
    assert updated["frustration_detected"] is True
    assert updated["route_decision"] == "escalate"


def test_router_escalates_on_repeated_failed_turns():
    state = make_state("I still need help.")
    state.failed_turn_count = 2

    updated = router_node(state)

    assert updated["escalation_needed"] is True
    assert updated["route_decision"] == "escalate"


def test_answer_node_projects_escalation_signal(monkeypatch):
    async def fake_grounded_answer(state, config=None, cohort=None):
        return {
            "messages": [
                AIMessage(
                    content="I do not have enough approved information.",
                    additional_kwargs={
                        "grounding": {
                            "grounded": False,
                            "needs_escalation": True,
                            "escalation_reason": "insufficient_context",
                            "sources": [],
                        }
                    },
                )
            ]
        }

    monkeypatch.setattr("app.graph.graph.grounded_answer", fake_grounded_answer)

    state = make_state("What is the exact updated deadline?")
    result = asyncio.run(answer_node(state))

    assert result["answer_generated"] is True
    assert result["answer_escalation_signal"] is True
    assert result["answer_escalation_reason"] == "insufficient_context"
    assert result["failed_turn_count"] == 1


def test_escalate_node_stores_ticket_id(monkeypatch):
    async def fake_trigger_answering_escalation(**kwargs):
        class Result:
            ticket_id = "esc_abc123"

        return Result()

    monkeypatch.setattr(
        "app.graph.graph.trigger_answering_escalation",
        fake_trigger_answering_escalation,
    )

    state = make_state("I want a human.")
    state.escalation_context = EscalationContext(
        trigger_reason="explicit_human_request",
        problem="I want a human.",
        what_was_tried="The assistant handled the message in the automated flow.",
        context="Session session_123 requires human support.",
        suggested_next_step="Review the learner issue and continue support through Ops.",
        summary="Learner requested human support.",
        user_goal="I want a human.",
    )

    result = asyncio.run(escalate_node(state))

    assert result["ticket_id"] == "esc_abc123"
    assert result["route_decision"] == "escalate"


def test_phase1_graph_builds():
    compiled = build_phase1_graph()
    assert compiled is not None
