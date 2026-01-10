"""
Example Tools and Agents
========================

This module contains example tools and agent configurations
for demonstrating Kafka agent capabilities.
"""

from .tools import (
    get_weather,
    count_slowly,
    get_weather_tool,
    count_tool,
    DEFAULT_MCP_SERVERS,
)
from .agent import create_example_agent

__all__ = [
    # Tool handlers
    "get_weather",
    "count_slowly",
    # Pre-configured tools
    "get_weather_tool",
    "count_tool",
    # Config
    "DEFAULT_MCP_SERVERS",
    # Agent factory
    "create_example_agent",
]
