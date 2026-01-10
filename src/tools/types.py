"""
Tool Types
==========

This module contains all the type definitions for the tool provider system.
These types are shared across all tool providers.
"""

from typing import Optional, List, Any, Dict, Callable, Awaitable, Union, AsyncGenerator, TYPE_CHECKING
from pydantic import BaseModel, Field
import asyncio
import inspect

if TYPE_CHECKING:
    from src.sandbox.base import Sandbox


# Type alias for tool handlers
# Can be: sync func, async func, or async generator (for streaming)
ToolHandler = Callable[..., Union[Any, Awaitable[Any], AsyncGenerator[str, None]]]


class ToolResultChunk(BaseModel):
    """
    A chunk of a streaming tool result.
    
    Attributes:
        tool_call_id: ID of the tool call this chunk belongs to
        tool_name: Name of the tool
        delta: The incremental content
        is_complete: Whether this is the final chunk
    """
    tool_call_id: str = Field(..., description="ID of the tool call")
    tool_name: str = Field(..., description="Name of the tool")
    delta: str = Field(default="", description="Incremental content")
    is_complete: bool = Field(default=False, description="Whether this is the final chunk")


class Tool:
    """
    A tool that can be executed by an LLM agent.
    
    This class encapsulates a tool's definition and execution logic.
    It provides an OpenAI-compatible definition and handles both
    sync and async handlers.
    
    Attributes:
        name: The unique name of the tool
        description: Human-readable description of what the tool does
        parameters: JSON Schema describing the tool's parameters
        handler: The function to execute when the tool is called
    
    Example:
        >>> async def get_weather(location: str) -> str:
        ...     return f"Weather in {location}: Sunny"
        >>> 
        >>> tool = Tool(
        ...     name="get_weather",
        ...     description="Get the weather for a location",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {
        ...             "location": {"type": "string", "description": "City name"}
        ...         },
        ...         "required": ["location"]
        ...     },
        ...     handler=get_weather
        ... )
        >>> 
        >>> # Get OpenAI-compatible definition
        >>> tool.definition
        >>> 
        >>> # Execute the tool
        >>> result = await tool.run({"location": "NYC"})
    """
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Optional[ToolHandler] = None
    ):
        """
        Initialize a tool.
        
        Args:
            name: Unique identifier for the tool
            description: Human-readable description of the tool's purpose
            parameters: JSON Schema describing the expected parameters
            handler: Optional async/sync function to execute. Can be set later.
        """
        self._name = name
        self._description = description
        self._parameters = parameters
        self._handler = handler
    
    @property
    def name(self) -> str:
        """Get the tool name."""
        return self._name
    
    @property
    def description(self) -> str:
        """Get the tool description."""
        return self._description
    
    @property
    def parameters(self) -> Dict[str, Any]:
        """Get the tool parameters schema."""
        return self._parameters
    
    @property
    def definition(self) -> Dict[str, Any]:
        """
        Get OpenAI-compatible tool definition.
        
        Returns:
            Dict in OpenAI's function calling format, ready to be
            passed to the API's tools parameter.
        """
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": self._parameters
            }
        }
    
    @property
    def has_handler(self) -> bool:
        """Check if a handler is registered."""
        return self._handler is not None
    
    @property
    def is_streaming(self) -> bool:
        """Check if the handler is a streaming async generator."""
        if self._handler is None:
            return False
        return inspect.isasyncgenfunction(self._handler)
    
    def set_handler(self, handler: ToolHandler) -> None:
        """
        Set or update the tool's handler.
        
        Args:
            handler: Async or sync function, or async generator for streaming
        """
        self._handler = handler
    
    async def run(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute the tool with the given arguments (non-streaming).
        
        For streaming tools, this collects all chunks and returns the full result.
        
        Args:
            arguments: Dictionary of arguments matching the parameters schema
        
        Returns:
            The result from the handler function
        
        Raises:
            ToolProviderError: If no handler is registered or execution fails
        """
        if self._handler is None:
            raise ToolProviderError(
                f"No handler registered for tool '{self._name}'",
                tool_name=self._name
            )
        
        # Handle streaming handlers - collect all chunks
        if inspect.isasyncgenfunction(self._handler):
            chunks = []
            async for chunk in self._handler(**arguments):
                chunks.append(chunk)
            return "".join(chunks)
        
        # Handle async handlers
        if asyncio.iscoroutinefunction(self._handler):
            return await self._handler(**arguments)
        
        # Handle sync handlers
        return self._handler(**arguments)
    
    async def run_stream(self, arguments: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        Execute the tool with streaming output.
        
        For non-streaming tools, yields the result as a single chunk.
        
        Args:
            arguments: Dictionary of arguments matching the parameters schema
        
        Yields:
            String chunks of the tool output
        
        Raises:
            ToolProviderError: If no handler is registered
        """
        if self._handler is None:
            raise ToolProviderError(
                f"No handler registered for tool '{self._name}'",
                tool_name=self._name
            )
        
        # Handle streaming handlers - yield chunks directly
        if inspect.isasyncgenfunction(self._handler):
            async for chunk in self._handler(**arguments):
                yield chunk
        elif asyncio.iscoroutinefunction(self._handler):
            # Async but not generator - yield result as single chunk
            result = await self._handler(**arguments)
            yield str(result)
        else:
            # Sync handler - yield result as single chunk
            result = self._handler(**arguments)
            yield str(result)


class SandboxTool:
    """
    A tool that executes inside a sandbox environment.
    
    Unlike regular Tool which has a local handler, SandboxTool
    forwards execution to a Sandbox's run_tool method.
    
    Attributes:
        name: The unique name of the tool
        description: Human-readable description of what the tool does
        parameters: JSON Schema describing the tool's parameters
        sandbox: The sandbox instance to execute in
    
    Example:
        >>> sandbox = await DaytonaSandbox.connect("my-sandbox-id")
        >>> await sandbox.wait_until_live()
        >>> 
        >>> tool = SandboxTool(
        ...     name="run_code",
        ...     description="Execute Python code in the sandbox",
        ...     parameters={
        ...         "type": "object",
        ...         "properties": {
        ...             "code": {"type": "string", "description": "Python code to run"}
        ...         },
        ...         "required": ["code"]
        ...     },
        ...     sandbox=sandbox
        ... )
        >>> 
        >>> # Execute the tool (streams from sandbox)
        >>> async for chunk in tool.run_stream({"code": "print('hello')"}):
        ...     print(chunk, end="")
    """
    
    DEFAULT_HEALTH_TIMEOUT = 60  # seconds
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        sandbox: "Sandbox",
        health_timeout: Optional[float] = None
    ):
        """
        Initialize a sandbox tool.
        
        Args:
            name: Unique identifier for the tool
            description: Human-readable description of the tool's purpose
            parameters: JSON Schema describing the expected parameters
            sandbox: The Sandbox instance to execute in
            health_timeout: Timeout in seconds to wait for sandbox to be healthy
                           before running. Defaults to 60 seconds.
        """
        self._name = name
        self._description = description
        self._parameters = parameters
        self._sandbox = sandbox
        self._health_timeout = health_timeout or self.DEFAULT_HEALTH_TIMEOUT
    
    @property
    def name(self) -> str:
        """Get the tool name."""
        return self._name
    
    @property
    def description(self) -> str:
        """Get the tool description."""
        return self._description
    
    @property
    def parameters(self) -> Dict[str, Any]:
        """Get the tool parameters schema."""
        return self._parameters
    
    @property
    def sandbox(self) -> "Sandbox":
        """Get the sandbox instance."""
        return self._sandbox
    
    @property
    def definition(self) -> Dict[str, Any]:
        """
        Get OpenAI-compatible tool definition.
        
        Returns:
            Dict in OpenAI's function calling format.
        """
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": self._parameters
            }
        }
    
    @property
    def is_streaming(self) -> bool:
        """Sandbox tools always stream."""
        return True
    
    async def _ensure_healthy(self) -> None:
        """Wait for the sandbox to be healthy before running."""
        if not self._sandbox.is_running:
            await self._sandbox.wait_until_live(timeout=self._health_timeout)
    
    async def run(self, arguments: Dict[str, Any]) -> str:
        """
        Execute the tool in the sandbox (non-streaming).
        
        Waits for the sandbox to be healthy, then collects all output
        and returns as a single string.
        
        Args:
            arguments: Dictionary of arguments matching the parameters schema
        
        Returns:
            The combined output from the sandbox
            
        Raises:
            TimeoutError: If sandbox doesn't become healthy within timeout
        """
        await self._ensure_healthy()
        
        result_parts = []
        async for event in self._sandbox.run_tool(self._name, arguments):
            if event.data:
                result_parts.append(event.data)
        return "".join(result_parts)
    
    async def run_stream(self, arguments: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        Execute the tool in the sandbox with streaming output.
        
        Waits for the sandbox to be healthy, then streams output.
        
        Args:
            arguments: Dictionary of arguments matching the parameters schema
        
        Yields:
            String chunks of the tool output from the sandbox
            
        Raises:
            TimeoutError: If sandbox doesn't become healthy within timeout
        """
        await self._ensure_healthy()
        
        async for event in self._sandbox.run_tool(self._name, arguments):
            if event.data:
                yield event.data


class MCPServerConfig(BaseModel):
    """
    Configuration for an MCP server.
    
    MCP servers provide tools via the Model Context Protocol.
    They can be stdio-based (command) or HTTP-based (url).
    
    Attributes:
        name: Unique identifier for this server
        command: Command to execute for stdio transport
        args: Arguments to pass to the command
        url: URL for HTTP transport (alternative to command)
        env: Environment variables to set for the command
    """
    name: str = Field(..., description="Unique server identifier")
    command: Optional[str] = Field(None, description="Command for stdio transport")
    args: Optional[List[str]] = Field(default_factory=list, description="Command arguments")
    url: Optional[str] = Field(None, description="URL for HTTP transport")
    env: Optional[Dict[str, str]] = Field(default_factory=dict, description="Environment variables")


class ToolResult(BaseModel):
    """
    Result from executing a tool.
    
    Attributes:
        success: Whether the tool executed successfully
        result: The return value from the tool (if successful)
        error: Error message (if failed)
        tool_name: Name of the tool that was executed
    """
    success: bool = Field(..., description="Whether execution succeeded")
    result: Optional[Any] = Field(None, description="Tool return value")
    error: Optional[str] = Field(None, description="Error message if failed")
    tool_name: str = Field(..., description="Name of executed tool")


class ToolProviderError(Exception):
    """
    Base exception for tool provider errors.
    
    Attributes:
        message: Human-readable error message
        tool_name: Name of the tool involved (if applicable)
        original_error: The underlying exception if wrapping another error
    """
    
    def __init__(
        self,
        message: str,
        tool_name: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.tool_name = tool_name
        self.original_error = original_error
    
    def __str__(self) -> str:
        if self.tool_name:
            return f"[Tool: {self.tool_name}] {self.message}"
        return self.message


# Keep ToolDefinition for backward compatibility (deprecated)
class ToolDefinition(BaseModel):
    """
    DEPRECATED: Use Tool class instead.
    
    A tool definition following OpenAI's function calling format.
    """
    type: str = Field(default="function", description="Tool type")
    function: Dict[str, Any] = Field(..., description="Function specification")
    
    @property
    def name(self) -> str:
        """Get the function name."""
        return self.function.get("name", "")
    
    def to_tool(self, handler: Optional[ToolHandler] = None) -> Tool:
        """Convert to a Tool object."""
        return Tool(
            name=self.function.get("name", ""),
            description=self.function.get("description", ""),
            parameters=self.function.get("parameters", {}),
            handler=handler
        )
