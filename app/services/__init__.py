"""Public service exports for the application package.

Keep imports lazy so lightweight services can be imported in isolation.
"""

from importlib import import_module


_EXPORTS = {
    "database_service": "app.services.database",
    "LLMRegistry": "app.services.llm",
    "llm_service": "app.services.llm",
    "EscalationTrigger": "app.services.escalation",
    "NoopEscalationTrigger": "app.services.escalation",
    "escalation_trigger": "app.services.escalation",
    "trigger_escalation": "app.services.escalation",
    "create_escalation_request": "app.services.escalation",
    "trigger_answering_escalation": "app.services.escalation",
    "trigger_proactive_escalation": "app.services.escalation",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Load service exports on demand."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
