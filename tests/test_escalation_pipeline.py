"""Unit tests for ``app.graph.nodes.escalation`` only.

These tests deliberately mock the ticket-service boundary. Persistence,
notifications, structured-summary generation, and ticket APIs belong in the
later end-to-end ``test_escalation_pipeline.py`` suite.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.graph.nodes.escalation as escalation_module
from app.graph.nodes.escalation import (
    EscalationTrigger,
    detect_escalation,
    escalation_node,
)


GROUNDING_FAILURE_REASONS = (
    "missing_question",
    "missing_cohort",
    "no_relevant_sources",
    "retrieval_error",
    "insufficient_context",
    "invalid_model_output",
    "invalid_citations",
    "llm_error",
)


def _failed_answer(reason: str = "insufficient_context") -> AIMessage:
    """Create an answer-node message that requests escalation."""
    return AIMessage(
        content="I couldn't find enough information in the approved materials.",
        additional_kwargs={
            "grounding": {
                "grounded": False,
                "needs_escalation": True,
                "escalation_reason": reason,
            }
        },
    )


def _grounded_answer(content: str = "The deadline is Thursday.") -> AIMessage:
    """Create a successful grounded answer message."""
    return AIMessage(
        content=content,
        additional_kwargs={
            "grounding": {
                "grounded": True,
                "needs_escalation": False,
                "escalation_reason": None,
            }
        },
    )


def _ticket_result(
    *,
    triggered: bool = True,
    ticket_id: str | None = "ticket-123",
    status: str = "open",
) -> SimpleNamespace:
    """Create the small result contract consumed by the node."""
    return SimpleNamespace(
        triggered=triggered,
        ticket_id=ticket_id,
        status=SimpleNamespace(value=status),
    )


@pytest.mark.parametrize("reason", GROUNDING_FAILURE_REASONS)
def test_detects_every_answer_escalation_reason(reason: str) -> None:
    state = {
        "messages": [
            HumanMessage(content="What should I do?"),
            _failed_answer(reason),
        ]
    }

    decision = detect_escalation(state)

    assert decision.should_escalate is True
    assert decision.trigger is EscalationTrigger.UNKNOWN_ANSWER
    assert reason in decision.reason
    assert decision.failure_count == 1


def test_detects_explicit_human_request() -> None:
    state = {"messages": [HumanMessage(content="Please open a support ticket for me.")]}

    decision = detect_escalation(state)

    assert decision.should_escalate is True
    assert decision.trigger is EscalationTrigger.EXPLICIT_REQUEST


def test_negated_request_does_not_trigger_escalation() -> None:
    state = {"messages": [HumanMessage(content="Please do not escalate this to a human agent.")]}

    decision = detect_escalation(state)

    assert decision.should_escalate is False
    assert decision.trigger is None


def test_detects_learner_frustration() -> None:
    state = {"messages": [HumanMessage(content="I'm very frustrated. You are not helping.")]}

    decision = detect_escalation(state)

    assert decision.should_escalate is True
    assert decision.trigger is EscalationTrigger.FRUSTRATION


def test_two_recent_failures_trigger_repeated_failures() -> None:
    state = {
        "messages": [
            HumanMessage(content="First question"),
            _failed_answer("no_relevant_sources"),
            HumanMessage(content="Let me ask again"),
            _failed_answer("insufficient_context"),
        ]
    }

    decision = detect_escalation(state)

    assert decision.should_escalate is True
    assert decision.trigger is EscalationTrigger.REPEATED_FAILURES
    assert decision.failure_count == 2


def test_grounded_answer_stops_old_failures_from_being_counted() -> None:
    state = {
        "messages": [
            HumanMessage(content="Old question"),
            _failed_answer(),
            HumanMessage(content="Resolved question"),
            _grounded_answer(),
            HumanMessage(content="Thanks"),
        ]
    }

    decision = detect_escalation(state)

    assert decision.should_escalate is False


def test_normal_conversation_does_not_escalate() -> None:
    state = {
        "messages": [
            HumanMessage(content="When is the deadline?"),
            _grounded_answer(),
        ]
    }

    decision = detect_escalation(state)

    assert decision.should_escalate is False


def test_supports_mapping_shaped_messages() -> None:
    state = {
        "messages": [
            {"role": "user", "content": "What is the deadline?"},
            {
                "role": "assistant",
                "content": "I could not find that information.",
                "additional_kwargs": {
                    "grounding": {
                        "grounded": False,
                        "needs_escalation": True,
                        "escalation_reason": "no_relevant_sources",
                    }
                },
            },
        ]
    }

    decision = detect_escalation(state)

    assert decision.should_escalate is True
    assert decision.trigger is EscalationTrigger.UNKNOWN_ANSWER


@pytest.mark.asyncio
async def test_node_returns_empty_update_when_escalation_is_not_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger_ticket = AsyncMock()
    monkeypatch.setattr(escalation_module, "_trigger_ticket", trigger_ticket)
    state = {
        "messages": [
            HumanMessage(content="When is the deadline?"),
            _grounded_answer(),
        ]
    }

    result = await escalation_node(state)

    assert result == {"messages": []}
    trigger_ticket.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_skips_duplicate_escalation_for_latest_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger_ticket = AsyncMock()
    monkeypatch.setattr(escalation_module, "_trigger_ticket", trigger_ticket)
    state = {
        "messages": [
            HumanMessage(content="Please open a support ticket."),
            AIMessage(
                content="A handoff was already attempted.",
                additional_kwargs={"escalation": {"attempted": True}},
            ),
        ]
    }

    result = await escalation_node(state)

    assert result == {"messages": []}
    trigger_ticket.assert_not_awaited()


@pytest.mark.asyncio
async def test_node_creates_confirmed_ticket_and_returns_ticket_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger_ticket = AsyncMock(return_value=_ticket_result())
    monkeypatch.setattr(escalation_module, "_trigger_ticket", trigger_ticket)
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Please open a support ticket. Contact me at ibrahim@example.com "
                    "or +20 100 123 4567. My key is api-abcdefghijklmnop."
                )
            )
        ]
    }
    config: dict[str, Any] = {
        "configurable": {"thread_id": "thread-7"},
        "metadata": {"user_id": "user-9"},
    }

    result = await escalation_node(state, config)

    trigger_ticket.assert_awaited_once()
    handoff = trigger_ticket.await_args.args[0]
    handoff_text = str(handoff)
    assert handoff["session_id"] == "thread-7"
    assert handoff["user_id"] == "user-9"
    assert "ibrahim@example.com" not in handoff_text
    assert "+20 100 123 4567" not in handoff_text
    assert "api-abcdefghijklmnop" not in handoff_text
    assert "[email redacted]" in handoff_text
    assert "[phone redacted]" in handoff_text
    assert "[secret redacted]" in handoff_text

    messages = result["messages"]
    assert len(messages) == 1
    message = messages[0]
    assert "ticket-123" in str(message.content)
    metadata = message.additional_kwargs["escalation"]
    assert metadata["attempted"] is True
    assert metadata["triggered"] is True
    assert metadata["confirmed"] is True
    assert metadata["trigger"] == "explicit_request"
    assert metadata["ticket_id"] == "ticket-123"
    assert metadata["status"] == "open"


@pytest.mark.asyncio
async def test_node_does_not_claim_success_without_ticket_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger_ticket = AsyncMock(
        return_value=_ticket_result(triggered=True, ticket_id=None),
    )
    monkeypatch.setattr(escalation_module, "_trigger_ticket", trigger_ticket)
    state = {"messages": [HumanMessage(content="Please escalate this.")]}

    result = await escalation_node(state)

    message = result["messages"][0]
    assert "couldn't confirm" in str(message.content).lower()
    metadata = message.additional_kwargs["escalation"]
    assert metadata["attempted"] is True
    assert metadata["triggered"] is True
    assert metadata["confirmed"] is False
    assert metadata["ticket_id"] is None


@pytest.mark.asyncio
async def test_node_returns_safe_fallback_when_ticket_service_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trigger_ticket = AsyncMock(side_effect=RuntimeError("database password leaked"))
    monkeypatch.setattr(escalation_module, "_trigger_ticket", trigger_ticket)
    state = {"messages": [HumanMessage(content="I want to speak with a human.")]}

    result = await escalation_node(state)

    message = result["messages"][0]
    assert "couldn't confirm" in str(message.content).lower()
    assert "database password leaked" not in str(message.content)
    metadata = message.additional_kwargs["escalation"]
    assert metadata == {
        "attempted": True,
        "triggered": False,
        "confirmed": False,
        "trigger": "explicit_request",
        "reason": "The learner explicitly requested human or Operations support.",
        "ticket_id": None,
        "status": "error",
        "error_code": "ticket_creation_failed",
    }