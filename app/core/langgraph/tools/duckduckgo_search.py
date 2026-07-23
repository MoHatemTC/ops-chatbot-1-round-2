"""DuckDuckGo search tool for LangGraph.

This module provides a DuckDuckGo search tool that can be used with LangGraph
to perform web searches. It returns up to 10 search results and handles errors
gracefully.
"""

import warnings
from langchain_community.tools import DuckDuckGoSearchResults

# Suppress deprecation warning for community tools
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain_community")

duckduckgo_search_tool = DuckDuckGoSearchResults(num_results=10, handle_tool_error=True)