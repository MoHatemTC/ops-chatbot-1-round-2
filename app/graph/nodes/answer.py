"""LangGraph node for retrieval-grounded Operations support answers.

This module coordinates the read side of Grounded Q&A without changing the
shared graph state or platform services. It extracts the learner's latest
question, retrieves approved cohort-scoped evidence, asks the platform LLM for
structured output, validates every citation, and returns either:

* a grounded answer with human-readable source attribution; or
* the approved honest-refusal message with escalation metadata.

All failure paths are fail-closed: retrieval, parsing, validation, or LLM
problems never fall back to general model knowledge.
"""

import os
from html import escape
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
)

from app.core.logging import logger
from app.prompts.grounding import (
    HONEST_REFUSAL_MESSAGE,
    GroundedAnswer,
    GroundingChunk,
    build_grounding_messages,
)
from app.retrieval.retriever import (
    RetrievedChunk,
    retrieve,
)
from app.schemas.graph import GraphState
from app.services.llm import llm_service

EscalationReason = Literal[
    "missing_question",
    "missing_cohort",
    "no_relevant_sources",
    "retrieval_error",
    "insufficient_context",
    "invalid_model_output",
    "invalid_citations",
    "llm_error",
]


class SourceAttribution(BaseModel):
    """Validated source metadata attached to a grounded answer."""

    alias: str
    citation_id: str
    source_id: str
    title: str
    source: str
    source_type: str
    cohort: str
    chunk_index: int = Field(ge=0)
    similarity: float = Field(ge=-1.0, le=1.0)


class AnswerOutcome(BaseModel):
    """Internal result shared by the answer generator and LangGraph node."""

    answer: str
    sources: list[SourceAttribution] = Field(default_factory=list)
    grounded: bool
    needs_escalation: bool
    escalation_reason: EscalationReason | None = None


def _normalise_text(value: Any) -> str:
    """Convert supported message content shapes to a stripped text string."""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    return ""


def _state_messages(state: GraphState | Mapping[str, Any]) -> Sequence[Any]:
    """Read messages from either the Pydantic graph state or a test mapping."""
    if isinstance(state, Mapping):
        messages = state.get("messages", [])
    else:
        messages = state.messages

    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes, bytearray)):
        return messages
    return []


def extract_latest_question(state: GraphState | Mapping[str, Any]) -> str:
    """Return the most recent learner/user message from the graph state."""
    for message in reversed(_state_messages(state)):
        if isinstance(message, Mapping):
            role = message.get("role") or message.get("type")
            content = message.get("content")
        else:
            role = getattr(message, "role", None) or getattr(message, "type", None)
            content = getattr(message, "content", None)

        if role in {"user", "human"}:
            return _normalise_text(content)

    return ""


def _mapping_value(container: Mapping[str, Any] | None, *keys: str) -> str:
    """Return the first non-empty string found under the supplied keys."""
    if not container:
        return ""
    for key in keys:
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_cohort(
    state: GraphState | Mapping[str, Any],
    config: RunnableConfig | None = None,
    *,
    explicit_cohort: str | None = None,
) -> str:
    """Resolve the cohort without weakening cross-cohort isolation.

    Resolution order is explicit argument, state, LangGraph configurable data,
    LangGraph metadata, then the deployment-level 'DEFAULT_COHORT' variable.
    The environment fallback supports a single-cohort Sprint 1 deployment while
    later graph wiring can pass a per-user cohort through the runnable config.
    """
    candidates: list[str] = []
    if explicit_cohort:
        candidates.append(explicit_cohort)

    if isinstance(state, Mapping):
        candidates.append(_mapping_value(state, "cohort", "cohort_id"))
    else:
        for attribute in ("cohort", "cohort_id"):
            value = getattr(state, attribute, None)
            if isinstance(value, str):
                candidates.append(value)

    if config:
        configurable = config.get("configurable")
        metadata = config.get("metadata")
        if isinstance(configurable, Mapping):
            candidates.append(_mapping_value(configurable, "cohort", "cohort_id"))
        if isinstance(metadata, Mapping):
            candidates.append(_mapping_value(metadata, "cohort", "cohort_id"))

    candidates.append(os.getenv("DEFAULT_COHORT", ""))
    return next((candidate.strip() for candidate in candidates if candidate.strip()), "")


def _refusal(reason: EscalationReason) -> AnswerOutcome:
    """Create the single safe learner-facing fallback used by every failure path."""
    return AnswerOutcome(
        answer=HONEST_REFUSAL_MESSAGE,
        grounded=False,
        needs_escalation=True,
        escalation_reason=reason,
    )


def _deduplicate_and_scope_chunks(
    chunks: Sequence[RetrievedChunk],
    *,
    cohort: str,
) -> list[RetrievedChunk]:
    """Keep unique, non-empty chunks belonging to the requested cohort only."""
    unique: list[RetrievedChunk] = []
    seen_citations: set[str] = set()

    for chunk in chunks:
        if chunk.cohort.strip() != cohort or not chunk.content.strip():
            continue
        if chunk.citation_id in seen_citations:
            continue
        seen_citations.add(chunk.citation_id)
        unique.append(chunk)

    return unique


def _citations_are_valid(
    response: GroundedAnswer,
    citation_map: Mapping[str, RetrievedChunk],
    *,
    cohort: str,
) -> bool:
    """Verify all model citations came from retrieved evidence for this cohort."""
    if not response.sufficient_context or not response.answer or not response.citations:
        return False

    available_aliases = set(citation_map)
    cited_aliases = set(response.citations)
    if not cited_aliases.issubset(available_aliases):
        return False

    return all(citation_map[alias].cohort.strip() == cohort for alias in cited_aliases)


def _source_attributions(
    citations: Sequence[str],
    citation_map: Mapping[str, RetrievedChunk],
) -> list[SourceAttribution]:
    """Map validated model aliases back to trusted retriever metadata."""
    return [
        SourceAttribution(
            alias=alias,
            citation_id=citation_map[alias].citation_id,
            source_id=citation_map[alias].source_id,
            title=citation_map[alias].title,
            source=citation_map[alias].source,
            source_type=citation_map[alias].source_type,
            cohort=citation_map[alias].cohort,
            chunk_index=citation_map[alias].chunk_index,
            similarity=citation_map[alias].similarity,
        )
        for alias in citations
    ]


def _single_line(value: str) -> str:
    """Collapse source metadata to one display-safe line."""
    collapsed = " ".join(value.replace("\x00", "").split())
    return escape(collapsed, quote=False)


def _render_answer(answer: str, sources: Sequence[SourceAttribution]) -> str:
    """Append a visible source list so attribution survives the current API schema."""
    source_lines: list[str] = []
    for item in sources:
        title = _single_line(item.title) or "Approved material"
        origin = _single_line(item.source)
        location = f" — {origin}" if origin and origin != title else ""
        source_lines.append(f"- [{item.alias}] {title}{location} (chunk {item.chunk_index})")

    return f"{answer.strip()}\n\nSources:\n" + "\n".join(source_lines)


async def generate_grounded_answer(
    question: str,
    *,
    cohort: str,
) -> AnswerOutcome:
    """Retrieve evidence, generate a structured answer, and validate citations.

    Args:
        question: The learner's current question.
        cohort: Mandatory cohort scope for knowledge retrieval.

    Returns:
        A grounded answer outcome or an honest refusal. No exception escapes to
        a caller merely because grounding infrastructure failed.
    """
    normalized_question = " ".join(question.split())
    normalized_cohort = cohort.strip()
    if not normalized_question:
        return _refusal("missing_question")
    if not normalized_cohort:
        return _refusal("missing_cohort")

    try:
        retrieved = await retrieve(normalized_question, cohort=normalized_cohort)
    except Exception as exc:
        logger.exception(
            "grounded_answer_retrieval_failed",
            cohort=normalized_cohort,
            error=str(exc),
        )
        return _refusal("retrieval_error")

    chunks = _deduplicate_and_scope_chunks(retrieved, cohort=normalized_cohort)
    if not chunks:
        logger.info("grounded_answer_no_relevant_sources", cohort=normalized_cohort)
        return _refusal("no_relevant_sources")

    try:
        grounding_chunks = cast(Sequence[GroundingChunk], chunks)
        messages, raw_citation_map = build_grounding_messages(normalized_question, grounding_chunks)
        citation_map = cast(dict[str, RetrievedChunk], raw_citation_map)
        raw_response = await llm_service.call(messages, response_format=GroundedAnswer)
        response = (
            raw_response if isinstance(raw_response, GroundedAnswer) else GroundedAnswer.model_validate(raw_response)
        )
    except ValidationError as exc:
        logger.warning(
            "grounded_answer_invalid_model_output",
            cohort=normalized_cohort,
            error=str(exc),
        )
        return _refusal("invalid_model_output")
    except Exception as exc:
        logger.exception(
            "grounded_answer_llm_failed",
            cohort=normalized_cohort,
            error=str(exc),
        )
        return _refusal("llm_error")

    if not response.sufficient_context:
        logger.info("grounded_answer_context_insufficient", cohort=normalized_cohort)
        return _refusal("insufficient_context")

    if not _citations_are_valid(response, citation_map, cohort=normalized_cohort):
        logger.warning(
            "grounded_answer_citation_validation_failed",
            cohort=normalized_cohort,
            citations=response.citations,
            available_citations=list(citation_map),
        )
        return _refusal("invalid_citations")

    sources = _source_attributions(response.citations, citation_map)
    rendered_answer = _render_answer(response.answer, sources)
    logger.info(
        "grounded_answer_generated",
        cohort=normalized_cohort,
        source_count=len(sources),
    )
    return AnswerOutcome(
        answer=rendered_answer,
        sources=sources,
        grounded=True,
        needs_escalation=False,
    )


async def grounded_answer(
    state: GraphState | Mapping[str, Any],
    config: RunnableConfig | None = None,
    *,
    cohort: str | None = None,
) -> dict[str, list[AIMessage]]:
    """LangGraph node that adds one grounded answer or refusal message.

    Grounding details are stored in 'AIMessage.additional_kwargs' so the
    shared 'GraphState' needs no modification. Source attribution is also
    rendered into the message content because the current REST response schema
    exposes only role and content.
    """
    question = extract_latest_question(state)
    resolved_cohort = resolve_cohort(state, config, explicit_cohort=cohort)
    outcome = await generate_grounded_answer(question, cohort=resolved_cohort)

    message = AIMessage(
        content=outcome.answer,
        additional_kwargs={
            "grounding": {
                "grounded": outcome.grounded,
                "needs_escalation": outcome.needs_escalation,
                "escalation_reason": outcome.escalation_reason,
                "sources": [source.model_dump() for source in outcome.sources],
            }
        },
    )
    return {"messages": [message]}


# Friendly alias for graph builders or tests that name nodes after their file.
answer_node = grounded_answer

__all__ = [
    "AnswerOutcome",
    "SourceAttribution",
    "answer_node",
    "extract_latest_question",
    "generate_grounded_answer",
    "grounded_answer",
    "resolve_cohort",
]
