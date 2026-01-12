"""
Server Tools
============

Tool definitions for the Kafka agent server.
"""

from .weather import get_weather_tool
from .counter import count_tool
from .shell import ShellTools
from .planner import PlannerTools
from .mcp_servers import DEFAULT_MCP_SERVERS
from .notebook import NotebookTools, get_notebook_mcp_server, NOTEBOOK_MCP_SERVER

__all__ = [
    "get_weather_tool",
    "count_tool",
    "ShellTools",
    "PlannerTools",
    "NotebookTools",
    "DEFAULT_MCP_SERVERS",
    "get_notebook_mcp_server",
    "NOTEBOOK_MCP_SERVER",
]
