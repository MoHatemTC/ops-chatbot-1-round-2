"""Public schema exports for the application package.

This module keeps imports lazy so consumers can load a single schema module
without pulling in unrelated optional dependencies.
"""

from importlib import import_module


_EXPORTS = {
    "Token": "app.schemas.auth",
    "BaseResponse": "app.schemas.base",
    "ChatRequest": "app.schemas.chat",
    "ChatResponse": "app.schemas.chat",
    "Message": "app.schemas.chat",
    "StreamResponse": "app.schemas.chat",
    "GraphState": "app.schemas.graph",
    "ConversationSummary": "app.schemas.escalation",
    "EscalationSource": "app.schemas.escalation",
    "EscalationTriggerRequest": "app.schemas.escalation",
    "EscalationTriggerResult": "app.schemas.escalation",
    "Ticket": "app.schemas.escalation",
    "TicketStatus": "app.schemas.escalation",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Load schema exports on demand."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
