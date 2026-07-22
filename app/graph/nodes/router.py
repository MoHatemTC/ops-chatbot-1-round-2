"""Deterministic routing logic for escalation decisions."""

from difflib import SequenceMatcher
from typing import Any, Mapping

from langchain_core.runnables.config import RunnableConfig

from app.core.metrics import escalation_routing_total
from app.core.observability import append_langfuse_tags
from app.graph.state import EscalationContext, SessionGraphState


FRUSTRATION_PHRASES = {
    "this is useless",
    "you are not helping",
    "i am frustrated",
    "this is frustrating",
    "i need real help",
    "this is not working",
    "i want a human",
    "let me talk to a human",
    "connect me to support",
}

HUMAN_SUPPORT_PHRASES = {
    "i want a human",
    "let me talk to a human",
    "connect me to support",
    "i need human help",
    "can i speak to a person",
}

FUZZY_MATCH_THRESHOLD = 0.86


def _latest_user_text(state: SessionGraphState) -> str:
    """Return the latest user/human message content as lowercase text."""
    for message in reversed(state.messages):
        role = getattr(message, "role", None) or getattr(message, "type", None)
        content = getattr(message, "content", "")

        if role in {"user", "human"} and isinstance(content, str):
            return content.strip().lower()

        if isinstance(message, Mapping):
            role = message.get("role") or message.get("type")
            content = message.get("content", "")
            if role in {"user", "human"} and isinstance(content, str):
                return content.strip().lower()

    return ""


def _phrase_matches(text: str, phrase: str, *, threshold: float = FUZZY_MATCH_THRESHOLD) -> bool:
    """Return True when text contains the phrase exactly or with a small typo."""
    if phrase in text:
        return True

    text_words = text.split()
    phrase_words = phrase.split()
    phrase_length = len(phrase_words)
    if phrase_length == 0 or len(text_words) < phrase_length:
        return False

    for start in range(len(text_words) - phrase_length + 1):
        candidate = " ".join(text_words[start : start + phrase_length])
        if SequenceMatcher(None, candidate, phrase).ratio() >= threshold:
            return True

    return False


def detect_explicit_human_request(state: SessionGraphState) -> bool:
    """Detect direct requests for human support."""
    text = _latest_user_text(state)
    return any(_phrase_matches(text, phrase) for phrase in HUMAN_SUPPORT_PHRASES)


def detect_frustration(state: SessionGraphState) -> bool:
    """Detect frustrated learner language deterministically."""
    text = _latest_user_text(state)
    return any(_phrase_matches(text, phrase) for phrase in FRUSTRATION_PHRASES)


def detect_repeated_failures(state: SessionGraphState, threshold: int = 2) -> bool:
    """Escalate after repeated failed turns."""
    return state.failed_turn_count >= threshold


def detect_answer_signal(state: SessionGraphState) -> bool:
    """Read escalation signal produced by the answer layer."""
    return state.answer_escalation_signal


def build_escalation_context(state: SessionGraphState) -> EscalationContext:
    """Build the structured escalation payload from graph state."""
    latest_user_text = _latest_user_text(state) or "Learner needs support."

    if state.explicit_human_requested:
        reason = "explicit_human_request"
    elif state.frustration_detected:
        reason = "frustration"
    elif detect_repeated_failures(state):
        reason = "repeated_failed_turns"
    else:
        reason = "answer_signal"

    return EscalationContext(
        trigger_reason=reason,
        problem=latest_user_text,
        what_was_tried="The assistant attempted to help in the automated flow before escalation.",
        context=f"Session {state.session_id or 'unknown'} requires human follow-up.",
        suggested_next_step="Review the learner issue and continue support through Ops.",
        summary="Learner issue needs human follow-up after automated handling could not safely complete it.",
        user_goal=latest_user_text,
        key_facts=[
            f"failed_turn_count={state.failed_turn_count}",
            f"answer_escalation_reason={state.answer_escalation_reason}",
        ],
        assistant_actions=[
            "Processed the learner message through the graph.",
            "Evaluated escalation triggers in router state.",
        ],
        open_questions=[
            "What exact help does the learner need from Ops?",
        ],
    )


def route_turn(state: SessionGraphState) -> str:
    """Return the next node name deterministically."""
    explicit_human_requested = detect_explicit_human_request(state)
    frustration_detected = detect_frustration(state)
    repeated_failures = detect_repeated_failures(state)
    answer_signal = detect_answer_signal(state)

    if explicit_human_requested or frustration_detected or repeated_failures or answer_signal:
        return "escalate"

    return "end"


def router_node(
    state: SessionGraphState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Router node that stores trigger flags and route decision in state."""
    explicit_human_requested = detect_explicit_human_request(state)
    frustration_detected = detect_frustration(state)
    repeated_failures = detect_repeated_failures(state)
    answer_signal = detect_answer_signal(state)

    escalation_needed = explicit_human_requested or frustration_detected or repeated_failures or answer_signal
    route_decision = "escalate" if escalation_needed else "end"
    trigger = (
        "explicit_human_request"
        if explicit_human_requested
        else "frustration"
        if frustration_detected
        else "repeated_failed_turns"
        if repeated_failures
        else "answer_signal"
        if answer_signal
        else "none"
    )

    if config:
        metadata = config.get("metadata")
        if isinstance(metadata, dict):
            append_langfuse_tags(
                metadata,
                "phase1-routing",
                f"route:{route_decision}",
                f"trigger:{trigger}",
            )

    escalation_routing_total.labels(route=route_decision, trigger=trigger).inc()

    update: dict[str, Any] = {
        "explicit_human_requested": explicit_human_requested,
        "frustration_detected": frustration_detected,
        "escalation_needed": escalation_needed,
        "route_decision": route_decision,
    }

    if escalation_needed:
        update["escalation_context"] = build_escalation_context(
            state.model_copy(
                update={
                    "explicit_human_requested": explicit_human_requested,
                    "frustration_detected": frustration_detected,
                }
            )
        )

    return update


def route_after_router(state: SessionGraphState) -> str:
    """LangGraph conditional edge function after router execution."""
    return "escalate" if state.escalation_needed else "end"
