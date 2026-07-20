"""Tests for escalation ticket schemas and scaffold trigger."""

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas.escalation import (
    ConversationSummary,
    EscalationSource,
    EscalationTriggerRequest,
    EscalationTriggerResult,
    Ticket,
    TicketStatus,
)
from app.services import escalation as escalation_service
from app.services.escalation import DatabaseEscalationTrigger, NoopEscalationTrigger

escalate_to_human_module = importlib.import_module("app.core.langgraph.tools.escalate_to_human")
escalate_to_human = escalate_to_human_module.escalate_to_human


def build_valid_ticket() -> Ticket:
    """Build a valid ticket for schema and service tests."""
    return Ticket(
        problem="Learner cannot find the assignment deadline.",
        what_was_tried="The assistant checked approved materials but did not find a grounded answer.",
        context="The learner asked about the current sprint assignment deadline.",
        suggested_next_step="Operations should confirm the deadline and update the approved materials if needed.",
        status=TicketStatus.OPEN,
    )


def build_valid_summary() -> ConversationSummary:
    """Build a privacy-preserving conversation summary."""
    return ConversationSummary(
        summary="Learner needs clarification on an assignment deadline.",
        user_goal="Know when the assignment is due.",
        key_facts=[
            "The answer was not found in approved materials.",
            "The assistant avoided giving an unsupported answer.",
        ],
        assistant_actions=[
            "Searched available approved context.",
            "Prepared an escalation handoff.",
        ],
        open_questions=[
            "What is the official assignment deadline?",
        ],
    )


def test_ticket_accepts_python_field_names_and_exports_kebab_case_aliases():
    ticket = build_valid_ticket()

    payload = ticket.model_dump(by_alias=True)

    assert payload["problem"] == "Learner cannot find the assignment deadline."
    assert payload["what-was-tried"].startswith("The assistant checked approved materials")
    assert payload["suggested-next-step"].startswith("Operations should confirm")
    assert payload["status"] == "open"


def test_ticket_accepts_shared_json_contract_aliases():
    ticket = Ticket.model_validate(
        {
            "problem": "Learner cannot access onboarding materials.",
            "what-was-tried": "The assistant checked approved FAQs and onboarding notes.",
            "context": "The learner says the onboarding link is unavailable.",
            "suggested-next-step": "Operations should verify the onboarding link and send the correct one.",
            "status": "open",
        }
    )

    assert ticket.what_was_tried.startswith("The assistant checked")
    assert ticket.suggested_next_step.startswith("Operations should")
    assert ticket.status == TicketStatus.OPEN


def test_ticket_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Ticket.model_validate(
            {
                "problem": "Learner has a schedule question.",
                "what-was-tried": "Assistant searched approved materials.",
                "context": "Question is about session timing.",
                "suggested-next-step": "Ops should confirm the schedule.",
                "status": "open",
                "raw_transcript": "This should not be accepted.",
            }
        )


def test_ticket_rejects_too_long_problem():
    with pytest.raises(ValidationError):
        Ticket(
            problem="x" * 801,
            what_was_tried="Assistant searched approved materials.",
            context="Question is about session timing.",
            suggested_next_step="Ops should confirm the schedule.",
        )


def test_conversation_summary_rejects_raw_transcript_field():
    with pytest.raises(ValidationError):
        ConversationSummary.model_validate(
            {
                "summary": "Learner needs support.",
                "user_goal": "Get a reliable answer.",
                "key_facts": ["No grounded answer was found."],
                "assistant_actions": ["Assistant prepared an escalation."],
                "open_questions": ["What should Ops tell the learner?"],
                "raw_transcript": "Full chat history should not be part of the summary contract.",
            }
        )


def test_escalation_trigger_request_shape():
    request = EscalationTriggerRequest(
        source=EscalationSource.ANSWERING,
        reason="No grounded answer found in approved Operations materials.",
        ticket=build_valid_ticket(),
        conversation_summary=build_valid_summary(),
        session_id="session_123",
        user_id="user_456",
    )

    assert request.source == EscalationSource.ANSWERING
    assert request.ticket.status == TicketStatus.OPEN
    assert request.conversation_summary.summary.startswith("Learner needs clarification")


def test_noop_escalation_trigger_returns_stable_result():
    request = EscalationTriggerRequest(
        source=EscalationSource.ANSWERING,
        reason="No grounded answer found in approved Operations materials.",
        ticket=build_valid_ticket(),
        conversation_summary=build_valid_summary(),
        session_id="session_123",
        user_id="user_456",
    )

    result = asyncio.run(NoopEscalationTrigger().trigger(request))

    assert result.triggered is True
    assert result.status == request.ticket.status
    assert result.ticket_id is None
    assert "No external ticket was created" in result.message


def test_database_escalation_trigger_returns_persisted_ticket_id(monkeypatch: pytest.MonkeyPatch):
    request = EscalationTriggerRequest(
        source=EscalationSource.ANSWERING,
        reason="No grounded answer found in approved Operations materials.",
        ticket=build_valid_ticket(),
        conversation_summary=build_valid_summary(),
        session_id="session_123",
        user_id="user_456",
    )

    class FakeDatabaseService:
        async def create_escalation_ticket(self, **kwargs):
            assert kwargs["source"] == "answering"
            assert kwargs["session_id"] == "session_123"
            assert kwargs["user_id"] == "user_456"

            class TicketRecord:
                id = "esc_123abc"

            return TicketRecord()

    import sys
    import types

    fake_module = types.ModuleType("app.services.database")
    fake_module.database_service = FakeDatabaseService()
    monkeypatch.setitem(sys.modules, "app.services.database", fake_module)

    result = asyncio.run(DatabaseEscalationTrigger().trigger(request))

    assert result.triggered is True
    assert result.ticket_id == "esc_123abc"
    assert result.status == TicketStatus.OPEN
    assert "esc_123abc" in result.message


def test_trigger_answering_escalation_builds_valid_request(monkeypatch: pytest.MonkeyPatch):
    captured_request = None

    async def fake_trigger(request: EscalationTriggerRequest) -> EscalationTriggerResult:
        nonlocal captured_request
        captured_request = request
        return EscalationTriggerResult(triggered=True, status=request.ticket.status, ticket_id="esc_123")

    monkeypatch.setattr(
        escalation_service, "escalation_trigger", AsyncMock(trigger=AsyncMock(side_effect=fake_trigger))
    )

    result = asyncio.run(
        escalation_service.trigger_answering_escalation(
            reason="No grounded answer found in approved Operations materials.",
            problem="Learner cannot find the assignment deadline.",
            what_was_tried="Assistant searched approved materials.",
            context="The learner asked about the current sprint assignment deadline.",
            suggested_next_step="Operations should confirm the deadline.",
            summary="Learner needs clarification on an assignment deadline.",
            user_goal="Know when the assignment is due.",
            key_facts=["No grounded deadline was found."],
            assistant_actions=["Searched approved materials."],
            open_questions=["What is the official assignment deadline?"],
            session_id="session_123",
            user_id="user_456",
        )
    )

    assert result.triggered is True
    assert result.ticket_id == "esc_123"
    assert captured_request is not None
    assert captured_request.source == EscalationSource.ANSWERING
    assert captured_request.session_id == "session_123"
    assert captured_request.user_id == "user_456"
    assert captured_request.ticket.problem == "Learner cannot find the assignment deadline."


def test_trigger_proactive_escalation_uses_proactive_source(monkeypatch: pytest.MonkeyPatch):
    captured_request = None

    async def fake_trigger(request: EscalationTriggerRequest) -> EscalationTriggerResult:
        nonlocal captured_request
        captured_request = request
        return EscalationTriggerResult(triggered=True, status=request.ticket.status)

    monkeypatch.setattr(
        escalation_service, "escalation_trigger", AsyncMock(trigger=AsyncMock(side_effect=fake_trigger))
    )

    result = asyncio.run(
        escalation_service.trigger_proactive_escalation(
            reason="A proactive check found an unresolved onboarding blocker.",
            problem="Learner still cannot access onboarding materials.",
            what_was_tried="Assistant reviewed the existing onboarding guidance.",
            context="A follow-up automation flagged the same unresolved issue.",
            suggested_next_step="Operations should verify the onboarding link and follow up.",
            summary="A proactive check found an unresolved onboarding blocker.",
            user_goal="Access the onboarding materials.",
        )
    )

    assert result.triggered is True
    assert captured_request is not None
    assert captured_request.source == EscalationSource.PROACTIVE


def test_escalate_to_human_tool_triggers_answering_escalation(monkeypatch: pytest.MonkeyPatch):
    async def fake_trigger_answering_escalation(**kwargs):
        assert kwargs["session_id"] == "session_123"
        assert kwargs["user_id"] == "user_456"
        assert kwargs["problem"] == "Learner cannot find the assignment deadline."
        return EscalationTriggerResult(
            triggered=True,
            status=TicketStatus.OPEN,
            ticket_id="esc_456",
            message="Escalation captured.",
        )

    monkeypatch.setattr(
        escalate_to_human_module,
        "trigger_answering_escalation",
        fake_trigger_answering_escalation,
    )

    result = asyncio.run(
        escalate_to_human.ainvoke(
            {
                "reason": "No grounded answer found in approved Operations materials.",
                "problem": "Learner cannot find the assignment deadline.",
                "what_was_tried": "Assistant searched approved materials.",
                "context": "The learner asked about the current sprint assignment deadline.",
                "suggested_next_step": "Operations should confirm the deadline.",
                "summary": "Learner needs clarification on an assignment deadline.",
                "user_goal": "Know when the assignment is due.",
                "session_id": "session_123",
                "user_id": "user_456",
            }
        )
    )

    assert "operations team" in result.lower()
    assert "esc_456" in result
