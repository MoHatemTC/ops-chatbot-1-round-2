"""Consume escalation signals and hand unresolved conversations to Operations.

The node detects the four Sprint 2 triggers, builds a privacy-preserving handoff,
and delegates ticket persistence and Ops notification to the shared escalation
service. It never tells the learner that a ticket exists unless a ticket ID was
returned by that service.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables.config import RunnableConfig
from prometheus_client import Counter, Histogram

from app.core.logging import logger

if TYPE_CHECKING:
    from app.schemas.graph import GraphState

# Reasons currently emitted by the grounded-answer node when it cannot answer
# safely from approved materials.
_GROUNDING_FAILURE_REASONS = frozenset(
    {
        "missing_question",
        "missing_cohort",
        "no_relevant_sources",
        "retrieval_error",
        "insufficient_context",
        "invalid_model_output",
        "invalid_citations",
        "llm_error",
    }
)

_EXPLICIT_REQUEST_PATTERNS = (
    r"\b(?:talk|speak|chat)\s+(?:to|with)\s+(?:a\s+)?(?:human|person|agent|representative)\b",
    r"\b(?:human|live)\s+(?:agent|support)\b",
    r"\b(?:contact|reach)\s+(?:the\s+)?operations(?:\s+team)?\b",
    r"\b(?:please\s+)?escalate\b",
    r"\b(?:open|create|raise)\s+(?:a\s+)?(?:support\s+)?ticket\b",
)

_NEGATED_REQUEST_PATTERNS = (
    r"\bdo\s+not\s+escalate\b",
    r"\bdon['’]?t\s+escalate\b",
    r"\bno\s+(?:human|agent|ticket)\b",
)

_FRUSTRATION_PATTERNS = (
    r"\bi(?:'m| am)\s+(?:very\s+)?(?:frustrated|annoyed|upset|angry)\b",
    r"\bthis\s+is\s+(?:useless|not helpful|going nowhere)\b",
    r"\byou(?:'re| are)\s+not\s+(?:helping|answering|listening)\b",
    r"\bhow\s+many\s+times\b",
)

_ASSISTANT_FAILURE_PHRASES = (
    "couldn't find",
    "could not find",
    "not enough information",
    "insufficient information",
    "approved materials do not",
    "needs help from the operations team",
)

# Ticket/summary limits match the shared escalation schema. Truncating before
# validation prevents one unusually long message from breaking the pipeline.
_PROBLEM_LIMIT = 800
_TRIED_LIMIT = 1000
_CONTEXT_LIMIT = 1200
_NEXT_STEP_LIMIT = 800
_SUMMARY_LIMIT = 800
_USER_GOAL_LIMIT = 400
_REPEATED_FAILURE_THRESHOLD = 2
_RECENT_MESSAGE_WINDOW = 8

escalation_node_events_total = Counter(
    "escalation_node_events_total",
    "Escalation-node outcomes grouped by trigger and outcome.",
    ["trigger", "outcome"],
)

escalation_node_duration_seconds = Histogram(
    "escalation_node_duration_seconds",
    "Time spent creating an escalation handoff.",
    ["trigger"],
    buckets=[0.01, 0.05, 0.1, 0.3, 0.5, 1.0, 2.0, 5.0],
)


class EscalationTrigger(str, Enum):
    """Supported reasons for handing a conversation to Operations."""

    UNKNOWN_ANSWER = "unknown_answer"
    FRUSTRATION = "frustration"
    EXPLICIT_REQUEST = "explicit_request"
    REPEATED_FAILURES = "repeated_failures"


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    """Outcome of evaluating the current conversation for escalation."""

    should_escalate: bool
    trigger: EscalationTrigger | None = None
    reason: str = ""
    failure_count: int = 0


def _normalise_content(content: Any) -> str:
    """Convert common LangChain content shapes into plain text."""
    if isinstance(content, str):
        return " ".join(content.split())

    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return " ".join(" ".join(parts).split())

    return ""


def _message_text(message: BaseMessage | Mapping[str, Any] | Any | None) -> str:
    """Extract normalized plain text from a LangChain-compatible message."""
    if message is None:
        return ""
    content = message.get("content", "") if isinstance(message, Mapping) else getattr(message, "content", "")
    return _normalise_content(content)


def _message_metadata(message: BaseMessage | Mapping[str, Any] | Any) -> Mapping[str, Any]:
    """Return a message's additional metadata when it is mapping-shaped."""
    value = (
        message.get("additional_kwargs", {})
        if isinstance(message, Mapping)
        else getattr(message, "additional_kwargs", {})
    )
    return value if isinstance(value, Mapping) else {}


def _grounding_metadata(message: BaseMessage | Mapping[str, Any] | Any) -> Mapping[str, Any]:
    """Read the contract emitted by the grounded-answer node."""
    value = _message_metadata(message).get("grounding", {})
    return value if isinstance(value, Mapping) else {}


def _message_type(message: BaseMessage | Mapping[str, Any] | Any) -> str | None:
    """Return a normalized role/type for object- or mapping-shaped messages."""
    if isinstance(message, Mapping):
        role = message.get("type") or message.get("role")
    else:
        role = getattr(message, "type", None) or getattr(message, "role", None)
    if role == "user":
        return "human"
    if role == "assistant":
        return "ai"
    return role if isinstance(role, str) else None


def _latest_message(messages: Sequence[Any], message_type: str) -> BaseMessage | Mapping[str, Any] | Any | None:
    """Return the latest human or AI message from the conversation."""
    expected_class = HumanMessage if message_type == "human" else AIMessage
    for message in reversed(messages):
        if isinstance(message, expected_class) or _message_type(message) == message_type:
            return message
    return None


def _state_messages(state: "GraphState" | Mapping[str, Any]) -> list[Any]:
    """Read conversation messages from a graph state or a test mapping."""
    value = state.get("messages", []) if isinstance(state, Mapping) else state.messages
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    """Return whether text matches at least one case-insensitive pattern."""
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _is_explicit_request(text: str) -> bool:
    """Detect a direct human/ticket request while respecting negation."""
    return not _matches(text, _NEGATED_REQUEST_PATTERNS) and _matches(text, _EXPLICIT_REQUEST_PATTERNS)


def _is_grounding_failure(message: BaseMessage | Mapping[str, Any] | Any) -> bool:
    """Check whether an assistant message represents an unresolved answer."""
    grounding = _grounding_metadata(message)
    reason = grounding.get("escalation_reason")

    if grounding.get("needs_escalation") is True:
        return True
    if isinstance(reason, str) and reason in _GROUNDING_FAILURE_REASONS:
        return True

    # Text matching is only a compatibility fallback for older answer messages
    # that were created before the grounding metadata contract existed.
    text = _message_text(message).lower()
    return any(phrase in text for phrase in _ASSISTANT_FAILURE_PHRASES)


def _recent_failure_count(messages: list[Any]) -> int:
    """Count recent unresolved assistant attempts until a grounded answer appears."""
    count = 0
    for message in reversed(messages[-_RECENT_MESSAGE_WINDOW:]):
        if not (isinstance(message, AIMessage) or _message_type(message) == "ai"):
            continue
        if _grounding_metadata(message).get("grounded") is True:
            break
        if _is_grounding_failure(message):
            count += 1
    return count


def detect_escalation(state: "GraphState" | Mapping[str, Any]) -> EscalationDecision:
    """Detect explicit requests, repeated failures, frustration, or unknown answers.

    Args:
        state: Current LangGraph state.

    Returns:
        The selected trigger and an internal reason, or a no-escalation result.
    """
    messages = _state_messages(state)
    latest_human = _latest_message(messages, "human")
    latest_ai = _latest_message(messages, "ai")
    learner_text = _message_text(latest_human).lower()

    if learner_text and _is_explicit_request(learner_text):
        return EscalationDecision(
            True,
            EscalationTrigger.EXPLICIT_REQUEST,
            "The learner explicitly requested human or Operations support.",
        )

    failure_count = _recent_failure_count(messages)
    if failure_count >= _REPEATED_FAILURE_THRESHOLD:
        return EscalationDecision(
            True,
            EscalationTrigger.REPEATED_FAILURES,
            f"The assistant had {failure_count} recent unresolved answer failures.",
            failure_count,
        )

    if learner_text and _matches(learner_text, _FRUSTRATION_PATTERNS):
        return EscalationDecision(
            True,
            EscalationTrigger.FRUSTRATION,
            "The learner expressed clear frustration with the support experience.",
        )

    if latest_ai is not None and _is_grounding_failure(latest_ai):
        reason = _grounding_metadata(latest_ai).get("escalation_reason", "unknown_answer")
        return EscalationDecision(
            True,
            EscalationTrigger.UNKNOWN_ANSWER,
            f"The grounded-answer flow could not resolve the request ({reason}).",
            1,
        )

    return EscalationDecision(False)


def _already_attempted_for_latest_turn(messages: list[Any]) -> bool:
    """Prevent duplicate tickets when LangGraph retries the same learner turn."""
    latest_human_index: int | None = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) or _message_type(message) == "human":
            latest_human_index = index
            break

    if latest_human_index is None:
        return False

    for message in messages[latest_human_index + 1 :]:
        escalation = _message_metadata(message).get("escalation", {})
        if isinstance(escalation, dict) and escalation.get("attempted") is True:
            return True
    return False


def _truncate(text: str, limit: int) -> str:
    """Normalize and truncate text to a shared-schema field limit."""
    value = " ".join(text.split()).strip() or "Not available."
    return value if len(value) <= limit else f"{value[: limit - 1].rstrip()}…"


def _redact_sensitive_text(text: str) -> str:
    """Remove common contact details and secrets from the ticket handoff."""
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email redacted]", text)
    value = re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", "[phone redacted]", value)
    return re.sub(r"\b(?:sk|api)[-_][A-Za-z0-9_-]{12,}\b", "[secret redacted]", value)


def _config_id(config: RunnableConfig | None, section: str, key: str) -> str | None:
    """Read a session or user identifier safely from RunnableConfig."""
    if config is None:
        return None
    values = config.get(section, {})
    if not isinstance(values, Mapping):
        return None
    value = values.get(key)
    return str(value) if value is not None else None


def _build_handoff(
    state: "GraphState" | Mapping[str, Any],
    decision: EscalationDecision,
    config: RunnableConfig | None,
) -> dict[str, Any]:
    """Create the ticket and structured-summary arguments for the shared service."""
    trigger = decision.trigger or EscalationTrigger.UNKNOWN_ANSWER
    latest_human = _latest_message(_state_messages(state), "human")
    learner_request = _truncate(_redact_sensitive_text(_message_text(latest_human)), _USER_GOAL_LIMIT)

    tried = {
        EscalationTrigger.UNKNOWN_ANSWER: (
            "The assistant searched approved Operations materials and refused to invent an unsupported answer."
        ),
        EscalationTrigger.FRUSTRATION: (
            "The assistant attempted to help in chat, but the learner reported that the issue remained unresolved."
        ),
        EscalationTrigger.EXPLICIT_REQUEST: "The assistant captured the learner's request for a human handoff.",
        EscalationTrigger.REPEATED_FAILURES: (
            "The assistant made repeated attempts but did not produce a satisfactory grounded resolution."
        ),
    }[trigger]

    next_step = {
        EscalationTrigger.UNKNOWN_ANSWER: (
            "Operations should confirm the correct guidance, reply to the learner, and update approved materials if needed."
        ),
        EscalationTrigger.FRUSTRATION: (
            "Operations should acknowledge the frustration, review the unresolved issue, and provide a clear resolution."
        ),
        EscalationTrigger.EXPLICIT_REQUEST: (
            "An Operations team member should review the request and contact the learner through an approved channel."
        ),
        EscalationTrigger.REPEATED_FAILURES: (
            "Operations should resolve the issue and identify the knowledge or workflow gap behind the repeated failures."
        ),
    }[trigger]

    key_facts = [
        f"Escalation trigger: {trigger.value}.",
        "The full conversation transcript is excluded from this handoff.",
    ]
    if decision.failure_count:
        key_facts.append(f"Recent unresolved assistant failures: {decision.failure_count}.")

    return {
        "reason": _truncate(decision.reason, 500),
        "problem": _truncate(f"Learner needs Operations support for: {learner_request}", _PROBLEM_LIMIT),
        "what_was_tried": _truncate(tried, _TRIED_LIMIT),
        "context": _truncate(
            f"Raised by the answering workflow because of {trigger.value}. Latest learner request: {learner_request}",
            _CONTEXT_LIMIT,
        ),
        "suggested_next_step": _truncate(next_step, _NEXT_STEP_LIMIT),
        "summary": _truncate(
            f"The learner needs human support after an escalation trigger: {trigger.value}.",
            _SUMMARY_LIMIT,
        ),
        "user_goal": learner_request,
        "key_facts": key_facts,
        "assistant_actions": [
            _truncate(tried, 400),
            "Prepared a privacy-preserving handoff without attaching the full chat transcript.",
        ],
        "open_questions": ["What verified guidance or action should Operations provide?"],
        "session_id": _config_id(config, "configurable", "thread_id"),
        "user_id": _config_id(config, "metadata", "user_id"),
    }


async def _trigger_ticket(handoff: dict[str, Any]) -> Any:
    """Delegate validation, persistence, and notification to the shared service.

    The local import lets this node be developed before the teammate's scaffold
    branch is merged into the working branch.
    """
    from app.services.escalation import trigger_answering_escalation

    return await trigger_answering_escalation(**handoff)


def _unconfirmed_message() -> str:
    """Return an honest response when ticket creation cannot be verified."""
    return (
        "This issue needs help from the Operations team, but I couldn't confirm that a support ticket was created. "
        "Please contact Operations directly through the approved support channel."
    )


async def escalation_node(
    state: "GraphState" | Mapping[str, Any],
    config: RunnableConfig | None = None,
) -> dict[str, list[AIMessage]]:
    """Create one support ticket for an escalated learner turn.

    Args:
        state: Current graph state containing conversation messages.
        config: Runnable configuration containing thread and user identifiers.

    Returns:
        A graph message update, or an empty update when escalation is unnecessary
        or has already been attempted for the latest learner turn.
    """
    decision = detect_escalation(state)
    trigger = decision.trigger.value if decision.trigger is not None else "none"

    if not decision.should_escalate:
        escalation_node_events_total.labels(trigger=trigger, outcome="not_triggered").inc()
        return {"messages": []}

    if _already_attempted_for_latest_turn(_state_messages(state)):
        escalation_node_events_total.labels(trigger=trigger, outcome="duplicate_skipped").inc()
        logger.info("escalation_duplicate_skipped", trigger=trigger)
        return {"messages": []}

    handoff = _build_handoff(state, decision, config)
    logger.info(
        "escalation_attempt_started",
        trigger=trigger,
        session_id=handoff["session_id"],
        user_id=handoff["user_id"],
    )

    try:
        with escalation_node_duration_seconds.labels(trigger=trigger).time():
            result = await _trigger_ticket(handoff)

        ticket_id_value = getattr(result, "ticket_id", None)
        ticket_id = str(ticket_id_value) if ticket_id_value else None
        triggered = getattr(result, "triggered", False) is True
        confirmed = triggered and ticket_id is not None
        outcome = "created" if confirmed else "unconfirmed"
        status = getattr(getattr(result, "status", "open"), "value", getattr(result, "status", "open"))

        escalation_node_events_total.labels(trigger=trigger, outcome=outcome).inc()
        logger.info(
            "escalation_attempt_completed",
            trigger=trigger,
            outcome=outcome,
            ticket_id=ticket_id,
            session_id=handoff["session_id"],
            user_id=handoff["user_id"],
        )

        content = (
            f"I've escalated this issue to the Operations team. Your support ticket ID is {ticket_id}."
            if confirmed
            else _unconfirmed_message()
        )
        return {
            "messages": [
                AIMessage(
                    content=content,
                    additional_kwargs={
                        "escalation": {
                            "attempted": True,
                            "triggered": triggered,
                            "confirmed": confirmed,
                            "trigger": trigger,
                            "reason": decision.reason,
                            "ticket_id": ticket_id,
                            "status": str(status),
                        }
                    },
                )
            ]
        }
    except Exception as exc:
        escalation_node_events_total.labels(trigger=trigger, outcome="error").inc()
        logger.exception(
            "escalation_attempt_failed",
            trigger=trigger,
            session_id=handoff["session_id"],
            user_id=handoff["user_id"],
            error_type=type(exc).__name__,
        )
        return {
            "messages": [
                AIMessage(
                    content=_unconfirmed_message(),
                    additional_kwargs={
                        "escalation": {
                            "attempted": True,
                            "triggered": False,
                            "confirmed": False,
                            "trigger": trigger,
                            "reason": decision.reason,
                            "ticket_id": None,
                            "status": "error",
                            "error_code": "ticket_creation_failed",
                        }
                    },
                )
            ]
        }


# Stable names for graph registration and unit tests.
escalation = escalation_node

__all__ = [
    "EscalationDecision",
    "EscalationTrigger",
    "detect_escalation",
    "escalation",
    "escalation_node",
]