"""LangGraph tools for enhanced language model capabilities.

This package contains custom tools that can be used with LangGraph to extend
the capabilities of language models. Currently includes tools for web search
and other external integrations.
"""

from langchain_core.tools.base import BaseTool

from .ask_human import ask_human
from .escalate_to_human import escalate_to_human

tools: list[BaseTool] = [ask_human, escalate_to_human]

try:
    from .duckduckgo_search import duckduckgo_search_tool
except ImportError:
    duckduckgo_search_tool = None
else:
    tools.insert(0, duckduckgo_search_tool)
