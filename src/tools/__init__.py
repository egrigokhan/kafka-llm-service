"""
Tools Module
============

This module provides tool management for LLM agents.

Exports:
- ToolProvider: Abstract base class for tool providers
- AgentToolProvider: Implementation that handles regular tools and MCP servers
- ToolDefinition: Model for tool definitions (OpenAI format)
- MCPServerConfig: Model for MCP server configuration
- ToolResult: Model for tool execution results
- ToolProviderError: Exception for tool-related errors

Usage:
------
```python
from src.tools import AgentToolProvider, ToolResult

# Create provider with tools and MCP servers
provider = AgentToolProvider(
    tools=[
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get the current time",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ],
    mcp_servers=[
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    ]
)

# Register handler for local tool
async def get_time():
    from datetime import datetime
    return datetime.now().isoformat()

provider.register_handler("get_time", get_time)

# Connect to MCP servers
await provider.connect()

# Get all tools (for sending to LLM)
tools = await provider.get_tools()

# Run a tool
result = await provider.run_tool("get_time", {})
print(result.result)  # Current time

# Clean up
await provider.disconnect()
```
"""

from .types import (
    Tool,
    SandboxTool,
    ToolDefinition,
    ToolResultChunk,
    MCPServerConfig,
    ToolResult,
    ToolProviderError,
)
from .base import ToolProvider
from .agent import AgentToolProvider

__all__ = [
    # Types
    "Tool",
    "SandboxTool",
    "ToolDefinition",
    "ToolResultChunk",
    "MCPServerConfig",
    "ToolResult",
    "ToolProviderError",
    # Providers
    "ToolProvider",
    "AgentToolProvider",
]
