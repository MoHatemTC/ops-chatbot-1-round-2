# Escalation & Ticket Contract

## Purpose

This document defines the escalation contract and answering-flow wiring for the Escalation & Tickets lane.

The implementation provides:

- a strict shared `Ticket` schema
- a privacy-preserving `ConversationSummary` schema
- an `EscalationTrigger` interface
- a default `NoopEscalationTrigger` implementation
- a database-backed `DatabaseEscalationTrigger` that stores internal ticket records
- an `escalate_to_human` LangGraph tool wired into the answering flow

This is groundwork for F1.4-F1.6. It now creates internal persisted ticket records, but it does not create real external third-party tickets yet.

## Scope

In scope:

- Define the shared escalation contract.
- Validate ticket and summary payloads with Pydantic.
- Provide an interface that answering and proactive flows can call.
- Provide helper entry points for both answering and proactive escalation callers.
- Log scaffold escalations in a structured way.
- Return a stable trigger result with a real internal `ticket_id`.
- Wire the answering flow to a real caller via the LangGraph tool layer.
- Persist internal escalation records in the application database.

Out of scope for this scaffold:

- External ticketing workspace integration.
- Ops ticket list/view/resolve APIs.
- Proactive automation that triggers escalations without an answering-tool call.

Those are follow-up implementation steps.

## Answering flow wiring

The answering flow now has a concrete integration point:

- the system prompt distinguishes `ask_human` from `escalate_to_human`
- the `escalate_to_human` tool builds a validated `EscalationTriggerRequest`
- the graph injects `session_id` and `user_id` from `GraphState` before invoking the tool
- the configured `escalation_trigger` handles the request and returns a stable handoff result

By default the app now uses `DatabaseEscalationTrigger`, which stores the escalation in the application database and returns a real internal ticket reference. If the database dependency is unavailable in a lightweight test environment, the code falls back to `NoopEscalationTrigger` so schema-level tests can still run in isolation.

For proactive callers, the service now also exposes a dedicated `trigger_proactive_escalation(...)` helper that builds the same validated contract with `source="proactive"`.

## Ticket schema

The shared ticket contract contains:

- `problem`: the learner's unresolved issue
- `what-was-tried`: what the assistant or learner already tried
- `context`: relevant non-sensitive context for Ops
- `suggested-next-step`: recommended human follow-up
- `status`: current ticket status

The public JSON contract supports kebab-case fields:

```json
{
  "problem": "Learner cannot find the assignment deadline.",
  "what-was-tried": "Assistant searched approved materials but did not find a grounded answer.",
  "context": "The learner asked about the current sprint assignment deadline.",
  "suggested-next-step": "Operations should confirm the deadline and update approved materials if needed.",
  "status": "open"
}
