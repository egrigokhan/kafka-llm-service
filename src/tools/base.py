"""
Tool Provider Base Class
========================

This module defines the abstract base class for tool providers in the system.
Tool providers manage both regular function tools and MCP (Model Context Protocol) servers.

The design follows these principles:
1. Support both regular tools (function dicts) and MCP servers
2. Async-first approach for MCP connections
3. Clear separation between tool registration and execution
4. Type-safe with Pydantic models

Usage Example:
-------------
```python
from src.tools import AgentToolProvider, Tool

# Create tools
get_weather = Tool(
    name="get_weather",
    description="Get the weather for a location",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name"}
        },
        "required": ["location"]
    },
    handler=lambda location: f"Weather in {location}: Sunny"
)

provider = AgentToolProvider(
    tools=[get_weather],
    mcp_servers=[
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    ]
)

await provider.connect()
tools = await provider.get_tools()
result = await provider.run_tool("get_weather", {"location": "NYC"})
```
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Any, Dict, Union

from src.tools.types import (
    Tool,
    ToolDefinition,
    MCPServerConfig,
    ToolResult,
    ToolProviderError,
)


# Re-export types for backward compatibility
__all__ = [
    "ToolProvider",
    "Tool",
    "ToolDefinition",
    "MCPServerConfig",
    "ToolResult",
    "ToolProviderError",
]


class ToolProvider(ABC):
    """
    Abstract base class for tool providers.
    
    This class defines the interface for managing tools from both
    regular function definitions and MCP servers.
    
    Subclasses MUST implement:
        - connect(): Connect to MCP servers
        - disconnect(): Disconnect from MCP servers  
        - get_tools(): Get all available tool definitions
        - run_tool(): Execute a specific tool
    
    Subclasses MAY override:
        - add_tool(): Add a new regular tool
        - add_mcp_server(): Add a new MCP server
    """
    
    def __init__(
        self,
        tools: Optional[List[Union[Tool, Dict[str, Any]]]] = None,
        mcp_servers: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Initialize the tool provider.
        
        Args:
            tools: List of Tool objects or tool definition dicts (OpenAI format).
                   Dicts should have "type" and "function" keys.
            mcp_servers: List of MCP server configurations.
                        Each should have at minimum "name" and either "command" or "url".
        """
        self._tools: Dict[str, Tool] = {}
        self._mcp_servers: List[MCPServerConfig] = []
        self._connected: bool = False
        
        # Parse and store initial tools
        if tools:
            for tool in tools:
                self.add_tool(tool)
        
        # Parse and store initial MCP servers
        if mcp_servers:
            for server in mcp_servers:
                self._mcp_servers.append(MCPServerConfig(**server))
    
    @abstractmethod
    async def connect(self) -> None:
        """
        Connect to all configured MCP servers.
        
        This should establish connections to all MCP servers and
        discover their available tools.
        
        Raises:
            ToolProviderError: If connection fails
        """
        ...
    
    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from all MCP servers.
        
        Clean up connections and resources.
        Safe to call multiple times.
        """
        ...
    
    @abstractmethod
    async def get_tools(self) -> List[Dict[str, Any]]:
        """
        Get all available tools from regular tools and MCP servers.
        
        Returns:
            List of tool definitions in OpenAI function format.
            Combines regular tools with tools discovered from MCP servers.
        """
        ...
    
    @abstractmethod
    async def run_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """
        Execute a tool by name with the given arguments.
        
        Args:
            name: The name of the tool to execute
            arguments: Arguments to pass to the tool
        
        Returns:
            ToolResult containing success status and result/error
        
        Raises:
            ToolProviderError: If tool not found or execution fails
        """
        ...
    
    def add_tool(self, tool: Union[Tool, Dict[str, Any]]) -> None:
        """
        Add a new tool.
        
        Args:
            tool: A Tool object or dict in OpenAI function format
        """
        if isinstance(tool, Tool):
            self._tools[tool.name] = tool
        elif isinstance(tool, dict):
            # Convert dict to Tool (backward compatibility)
            func = tool.get("function", {})
            new_tool = Tool(
                name=func.get("name", ""),
                description=func.get("description", ""),
                parameters=func.get("parameters", {})
            )
            self._tools[new_tool.name] = new_tool
        else:
            raise TypeError(f"Expected Tool or dict, got {type(tool)}")
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """
        Get a tool by name.
        
        Args:
            name: The name of the tool
        
        Returns:
            The Tool object, or None if not found
        """
        return self._tools.get(name)
    
    def add_mcp_server(self, server: Dict[str, Any]) -> None:
        """
        Add a new MCP server configuration.
        
        Note: You must call connect() again after adding a new server
        for it to become available.
        
        Args:
            server: MCP server configuration dict
        """
        self._mcp_servers.append(MCPServerConfig(**server))
    
    def get_regular_tools(self) -> List[Dict[str, Any]]:
        """
        Get just the regular (non-MCP) tools.
        
        Returns:
            List of tool definitions in OpenAI format
        """
        return [tool.definition for tool in self._tools.values()]
    
    def get_mcp_servers(self) -> List[Dict[str, Any]]:
        """
        Get list of configured MCP servers.
        
        Returns:
            List of MCP server configurations
        """
        return [s.model_dump() for s in self._mcp_servers]
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to MCP servers."""
        return self._connected
    
    @property
    def tool_names(self) -> List[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())
