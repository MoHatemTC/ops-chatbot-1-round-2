"""Escalation tool for routing unresolved issues to a human operator."""

from langchain_core.tools import tool

from app.services.escalation import trigger_answering_escalation


@tool
async def escalate_to_human(
    reason: str,
    problem: str,
    what_was_tried: str,
    context: str,
    suggested_next_step: str,
    summary: str,
    user_goal: str,
    key_facts: list[str] | None = None,
    assistant_actions: list[str] | None = None,
    open_questions: list[str] | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Create a structured Ops escalation when the assistant cannot safely finish the request.

    Use this when the user needs human follow-up or the answer cannot be grounded in approved
    information. Do not use it for ordinary clarifications from the user; use ask_human instead.
    """
    result = await trigger_answering_escalation(
        reason=reason,
        problem=problem,
        what_was_tried=what_was_tried,
        context=context,
        suggested_next_step=suggested_next_step,
        summary=summary,
        user_goal=user_goal,
        key_facts=key_facts,
        assistant_actions=assistant_actions,
        open_questions=open_questions,
        session_id=session_id,
        user_id=user_id,
    )

    if result.ticket_id:
        return (
            "I couldn't safely resolve this with the information available, so I prepared a handoff "
            f"for the operations team. Reference: {result.ticket_id}."
        )

    return (
        "I couldn't safely resolve this with the information available, so I prepared a structured "
        "handoff for the operations team."
    )
