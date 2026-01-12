"""
Agent Tool Provider
===================

Implementation of ToolProvider that connects to MCP servers and manages tools.

This provider:
- Manages regular function tools (Tool objects or dicts)
- Connects to MCP servers via stdio or HTTP transport
- Discovers tools from MCP servers
- Routes tool calls to the appropriate handler

Example:
-------
```python
from src.tools import AgentToolProvider, Tool

# Create a tool with handler
calculate_tool = Tool(
    name="calculate",
    description="Perform a calculation",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string"}
        },
        "required": ["expression"]
    },
    handler=lambda expression: str(eval(expression))
)

provider = AgentToolProvider(
    tools=[calculate_tool],
    mcp_servers=[
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    ]
)

await provider.connect()
tools = await provider.get_tools()  # Gets both regular + MCP tools
result = await provider.run_tool("calculate", {"expression": "2 + 2"})
```
"""

import json
import asyncio
from typing import Optional, List, Any, Dict, Union, AsyncGenerator

from .base import (
    ToolProvider,
    Tool,
    MCPServerConfig,
    ToolResult,
    ToolProviderError,
)
from .types import ToolHandler, SandboxTool, ToolResultChunk


class MCPConnection:
    """
    Represents a connection to an MCP server.
    
    This is a lightweight wrapper that manages the lifecycle of
    an MCP server connection and caches discovered tools.
    """
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.tools: List[Dict[str, Any]] = []
        self.connected: bool = False
        self._client: Any = None
        self._session: Any = None
        self._process: Optional[asyncio.subprocess.Process] = None
    
    async def connect(self) -> None:
        """Establish connection to the MCP server."""
        try:
            # Try to import mcp library
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise ToolProviderError(
                "MCP library not installed. Install with: pip install mcp",
                tool_name=self.config.name
            )
        
        if self.config.command:
            # Stdio transport
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args or [],
                env=self.config.env
            )
            
            # Create the stdio client context
            self._stdio_context = stdio_client(server_params)
            self._read, self._write = await self._stdio_context.__aenter__()
            
            # Create session
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()
            
            # Initialize the connection
            await self._session.initialize()
            
        elif self.config.url:
            # HTTP transport for remote MCP servers
            # Try streamable HTTP first (newer), then fall back to SSE
            connected = False
            
            try:
                from mcp.client.streamable_http import streamablehttp_client
                
                # Create the streamable HTTP client context
                self._http_context = streamablehttp_client(self.config.url)
                self._read, self._write, _ = await self._http_context.__aenter__()
                
                # Create session
                self._session = ClientSession(self._read, self._write)
                await self._session.__aenter__()
                
                # Initialize the connection
                await self._session.initialize()
                connected = True
            except Exception as e:
                # Fall back to SSE transport
                if hasattr(self, '_session') and self._session:
                    try:
                        await self._session.__aexit__(None, None, None)
                    except:
                        pass
                if hasattr(self, '_http_context') and self._http_context:
                    try:
                        await self._http_context.__aexit__(None, None, None)
                    except:
                        pass
                self._session = None
                self._http_context = None
            
            if not connected:
                try:
                    from mcp.client.sse import sse_client
                    
                    # Create the SSE client context
                    self._sse_context = sse_client(self.config.url)
                    self._read, self._write = await self._sse_context.__aenter__()
                    
                    # Create session
                    self._session = ClientSession(self._read, self._write)
                    await self._session.__aenter__()
                    
                    # Initialize the connection
                    await self._session.initialize()
                except ImportError:
                    raise ToolProviderError(
                        "MCP HTTP clients not available. Install with: pip install mcp",
                        tool_name=self.config.name
                    )
            
        else:
            raise ToolProviderError(
                f"MCP server {self.config.name} must have either 'command' or 'url'",
                tool_name=self.config.name
            )
        
        # Discover available tools
        await self._discover_tools()
        self.connected = True
    
    async def _discover_tools(self) -> None:
        """Discover tools from the connected MCP server."""
        if not self._session:
            return
        
        try:
            result = await self._session.list_tools()
            
            # Convert MCP tools to OpenAI function format
            for tool in result.tools:
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                    }
                }
                self.tools.append(tool_def)
                
        except Exception as e:
            raise ToolProviderError(
                f"Failed to discover tools from {self.config.name}: {e}",
                tool_name=self.config.name,
                original_error=e
            )
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on this MCP server."""
        if not self._session:
            raise ToolProviderError(
                f"Not connected to MCP server: {self.config.name}",
                tool_name=name
            )
        
        try:
            result = await self._session.call_tool(name, arguments)
            
            # Extract content from result
            if hasattr(result, 'content') and result.content:
                # MCP returns content as a list of content blocks
                contents = []
                for block in result.content:
                    if hasattr(block, 'text'):
                        contents.append(block.text)
                    elif hasattr(block, 'data'):
                        contents.append(block.data)
                    else:
                        contents.append(str(block))
                return "\n".join(contents) if contents else None
            return result
            
        except Exception as e:
            raise ToolProviderError(
                f"Failed to call tool {name}: {e}",
                tool_name=name,
                original_error=e
            )
    
    async def call_tool_stream(
        self, 
        name: str, 
        arguments: Dict[str, Any],
        broadcast_pipe: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Call a tool with streaming output via broadcast pipe.
        
        If broadcast_pipe is provided, reads streaming output from the pipe
        while the tool executes. Otherwise falls back to non-streaming.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            broadcast_pipe: Path to named pipe for streaming output (e.g., /tmp/kafka_broadcaster_pipe)
        
        Yields:
            Output chunks as they arrive
        """
        import os
        
        if not self._session:
            raise ToolProviderError(
                f"Not connected to MCP server: {self.config.name}",
                tool_name=name
            )
        
        # If no broadcast pipe or pipe doesn't exist, fall back to non-streaming
        if not broadcast_pipe or not os.path.exists(broadcast_pipe):
            result = await self.call_tool(name, arguments)
            if result:
                yield str(result)
            return
        
        # Queue for streaming chunks
        chunk_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        tool_done = asyncio.Event()
        final_result: List[Any] = [None]
        
        async def read_pipe():
            """Read from broadcast pipe and put chunks in queue."""
            try:
                # Open pipe for reading (non-blocking)
                loop = asyncio.get_event_loop()
                
                # Use os.open with O_RDONLY | O_NONBLOCK
                try:
                    fd = os.open(broadcast_pipe, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    return  # Pipe doesn't exist or can't be opened
                
                try:
                    buffer = ""
                    while not tool_done.is_set():
                        try:
                            # Try to read from pipe
                            data = os.read(fd, 4096)
                            if data:
                                buffer += data.decode('utf-8', errors='replace')
                                
                                # Process complete JSON messages (newline-delimited)
                                while '\n' in buffer:
                                    line, buffer = buffer.split('\n', 1)
                                    if line.strip():
                                        try:
                                            msg = json.loads(line)
                                            # Extract content from broadcast message
                                            if msg.get("delta", {}).get("content"):
                                                await chunk_queue.put(msg["delta"]["content"])
                                            elif msg.get("output"):
                                                # Done event - we'll get this from the tool result
                                                pass
                                        except json.JSONDecodeError:
                                            pass
                            else:
                                # No data, wait a bit
                                await asyncio.sleep(0.01)
                        except BlockingIOError:
                            await asyncio.sleep(0.01)
                        except Exception:
                            break
                finally:
                    os.close(fd)
            except Exception:
                pass
            finally:
                # Signal we're done reading
                await chunk_queue.put(None)
        
        async def call_tool_task():
            """Execute the tool call."""
            try:
                result = await self._session.call_tool(name, arguments)
                
                # Extract content
                if hasattr(result, 'content') and result.content:
                    contents = []
                    for block in result.content:
                        if hasattr(block, 'text'):
                            contents.append(block.text)
                        elif hasattr(block, 'data'):
                            contents.append(block.data)
                        else:
                            contents.append(str(block))
                    final_result[0] = "\n".join(contents) if contents else None
                else:
                    final_result[0] = result
            except Exception as e:
                final_result[0] = f"Error: {e}"
            finally:
                tool_done.set()
        
        # Start both tasks
        pipe_task = asyncio.create_task(read_pipe())
        tool_task = asyncio.create_task(call_tool_task())
        
        # Yield chunks as they arrive
        chunks_received = False
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
                    if chunk is None:
                        break
                    chunks_received = True
                    yield chunk
                except asyncio.TimeoutError:
                    if tool_done.is_set():
                        # Drain any remaining chunks
                        while not chunk_queue.empty():
                            chunk = chunk_queue.get_nowait()
                            if chunk is not None:
                                chunks_received = True
                                yield chunk
                        break
        finally:
            tool_done.set()
            pipe_task.cancel()
            try:
                await pipe_task
            except asyncio.CancelledError:
                pass
            await tool_task
        
        # If no chunks were received via pipe, yield the final result
        if not chunks_received and final_result[0]:
            yield str(final_result[0])
    
    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        
        if hasattr(self, '_stdio_context') and self._stdio_context:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_context = None
        
        if hasattr(self, '_sse_context') and self._sse_context:
            try:
                await self._sse_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._sse_context = None
        
        if hasattr(self, '_http_context') and self._http_context:
            try:
                await self._http_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._http_context = None
        
        self.connected = False
        self.tools = []


class AgentToolProvider(ToolProvider):
    """
    Tool provider implementation for AI agents.
    
    Manages regular function tools, MCP server connections, and sandbox tools.
    Tools from all sources are unified under a single interface.
    
    Attributes:
        _mcp_connections: Active MCP server connections
        _mcp_tool_map: Maps tool names to their MCP server
        _sandbox_tools: Sandbox tools that execute in a sandbox environment
    """
    
    def __init__(
        self,
        tools: Optional[List[Union[Tool, Dict[str, Any]]]] = None,
        mcp_servers: Optional[List[Dict[str, Any]]] = None,
        sandbox_tools: Optional[List[SandboxTool]] = None
    ):
        """
        Initialize the agent tool provider.
        
        Args:
            tools: List of Tool objects or tool definition dicts
            mcp_servers: List of MCP server configurations
            sandbox_tools: List of SandboxTool objects that execute in a sandbox
        """
        super().__init__(tools=tools, mcp_servers=mcp_servers)
        
        # MCP connections
        self._mcp_connections: Dict[str, MCPConnection] = {}
        
        # Sandbox tools (keyed by name)
        self._sandbox_tools: Dict[str, SandboxTool] = {}
        if sandbox_tools:
            for st in sandbox_tools:
                self._sandbox_tools[st.name] = st
        
        # Map tool names to their source (MCP server name, "local", or "sandbox")
        self._tool_source_map: Dict[str, str] = {}
    
    def register_handler(self, name: str, handler: ToolHandler) -> None:
        """
        Register a handler function for a tool.
        
        The handler will be called when run_tool is invoked for this tool.
        
        Args:
            name: Tool name (must match a tool definition name)
            handler: Async or sync function that implements the tool
        
        Example:
            >>> async def my_calculator(expression: str) -> str:
            ...     return str(eval(expression))
            >>> provider.register_handler("calculate", my_calculator)
        """
        tool = self.get_tool(name)
        if tool:
            tool.set_handler(handler)
        self._tool_source_map[name] = "local"
    
    async def connect(self) -> None:
        """
        Connect to all configured MCP servers.
        
        Establishes connections and discovers available tools.
        """
        for server_config in self._mcp_servers:
            try:
                connection = MCPConnection(server_config)
                await connection.connect()
                self._mcp_connections[server_config.name] = connection
                
                # Map discovered tools to this server
                for tool in connection.tools:
                    tool_name = tool["function"]["name"]
                    self._tool_source_map[tool_name] = server_config.name
                    
            except Exception as e:
                # Log but continue with other servers
                print(f"Warning: Failed to connect to MCP server {server_config.name}: {e}")
        
        # Mark local tools
        for tool_name in self._tools:
            if tool_name not in self._tool_source_map:
                self._tool_source_map[tool_name] = "local"
        
        # Mark sandbox tools
        for tool_name in self._sandbox_tools:
            self._tool_source_map[tool_name] = "sandbox"
        
        self._connected = True
    
    async def disconnect(self) -> None:
        """
        Disconnect from all MCP servers.
        """
        for connection in self._mcp_connections.values():
            await connection.disconnect()
        
        self._mcp_connections.clear()
        self._tool_source_map.clear()
        self._connected = False
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        """
        Get all available tools.
        
        Returns combined list of:
        - Regular tools (passed during init or via add_tool)
        - Tools discovered from MCP servers
        - Sandbox tools
        
        Returns:
            List of tool definitions in OpenAI function format
        """
        all_tools = []
        
        # Add regular tools
        all_tools.extend(self.get_regular_tools())
        
        # Add MCP tools
        for connection in self._mcp_connections.values():
            all_tools.extend(connection.tools)
        
        # Add sandbox tools
        for sandbox_tool in self._sandbox_tools.values():
            all_tools.append(sandbox_tool.definition)
        
        return all_tools
    
    async def run_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """
        Execute a tool by name.
        
        Routes the call to the appropriate handler:
        - Local tools: Uses the Tool's run method
        - MCP tools: Calls the MCP server
        - Sandbox tools: Calls the sandbox's run_tool method
        
        Args:
            name: Tool name
            arguments: Arguments to pass to the tool
        
        Returns:
            ToolResult with success status and result/error
        """
        source = self._tool_source_map.get(name)
        
        if source is None:
            return ToolResult(
                success=False,
                error=f"Tool not found: {name}",
                tool_name=name
            )
        
        try:
            if source == "local":
                # Call local tool
                tool = self.get_tool(name)
                if tool is None:
                    return ToolResult(
                        success=False,
                        error=f"Tool not found: {name}",
                        tool_name=name
                    )
                
                if not tool.has_handler:
                    return ToolResult(
                        success=False,
                        error=f"No handler registered for tool: {name}",
                        tool_name=name
                    )
                
                result = await tool.run(arguments)
                return ToolResult(
                    success=True,
                    result=result,
                    tool_name=name
                )
            
            elif source == "sandbox":
                # Call sandbox tool
                sandbox_tool = self._sandbox_tools.get(name)
                if sandbox_tool is None:
                    return ToolResult(
                        success=False,
                        error=f"Sandbox tool not found: {name}",
                        tool_name=name
                    )
                
                result = await sandbox_tool.run(arguments)
                return ToolResult(
                    success=True,
                    result=result,
                    tool_name=name
                )
            
            else:
                # Call MCP server
                connection = self._mcp_connections.get(source)
                if connection is None:
                    return ToolResult(
                        success=False,
                        error=f"MCP server not connected: {source}",
                        tool_name=name
                    )
                
                result = await connection.call_tool(name, arguments)
                return ToolResult(
                    success=True,
                    result=result,
                    tool_name=name
                )
                
        except ToolProviderError as e:
            return ToolResult(
                success=False,
                error=str(e),
                tool_name=name
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {e}",
                tool_name=name
            )
    
    async def run_tool_json(
        self,
        name: str,
        arguments_json: str
    ) -> ToolResult:
        """
        Execute a tool with JSON-encoded arguments.
        
        Convenience method for when arguments come as a JSON string
        (common with LLM function calling).
        
        Args:
            name: Tool name
            arguments_json: JSON string of arguments
        
        Returns:
            ToolResult with success status and result/error
        """
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                error=f"Invalid JSON arguments: {e}",
                tool_name=name
            )
        
        return await self.run_tool(name, arguments)
    
    async def run_tool_stream(
        self,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str
    ) -> AsyncGenerator[ToolResultChunk, None]:
        """
        Execute a tool with streaming output.
        
        Routes the call to the appropriate handler and streams results.
        
        Args:
            name: Tool name
            arguments: Arguments to pass to the tool
            tool_call_id: The ID of the tool call (for tracking)
        
        Yields:
            ToolResultChunk for each piece of output
        """
        source = self._tool_source_map.get(name)
        
        if source is None:
            yield ToolResultChunk(
                tool_call_id=tool_call_id,
                tool_name=name,
                delta=f"Error: Tool not found: {name}",
                is_complete=True
            )
            return
        
        try:
            if source == "sandbox":
                # Stream from sandbox tool
                sandbox_tool = self._sandbox_tools.get(name)
                if sandbox_tool is None:
                    yield ToolResultChunk(
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        delta=f"Error: Sandbox tool not found: {name}",
                        is_complete=True
                    )
                    return
                
                async for chunk in sandbox_tool.run_stream(arguments):
                    yield ToolResultChunk(
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        delta=chunk,
                        is_complete=False
                    )
                
                # Final chunk
                yield ToolResultChunk(
                    tool_call_id=tool_call_id,
                    tool_name=name,
                    delta="",
                    is_complete=True
                )
            
            elif source == "local":
                # Stream from local tool
                tool = self.get_tool(name)
                if tool is None or not tool.has_handler:
                    yield ToolResultChunk(
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        delta=f"Error: Tool not found or no handler: {name}",
                        is_complete=True
                    )
                    return
                
                async for chunk in tool.run_stream(arguments):
                    yield ToolResultChunk(
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        delta=chunk,
                        is_complete=False
                    )
                
                # Final chunk
                yield ToolResultChunk(
                    tool_call_id=tool_call_id,
                    tool_name=name,
                    delta="",
                    is_complete=True
                )
            
            else:
                # MCP tools - stream via broadcast pipe if available
                connection = self._mcp_connections.get(source)
                if connection is None:
                    yield ToolResultChunk(
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        delta=f"Error: MCP server not connected: {source}",
                        is_complete=True
                    )
                    return
                
                # Try streaming via broadcast pipe (used by notebook MCP server)
                broadcast_pipe = "/tmp/kafka_broadcaster_pipe"
                has_chunks = False
                
                async for chunk in connection.call_tool_stream(name, arguments, broadcast_pipe):
                    has_chunks = True
                    yield ToolResultChunk(
                        tool_call_id=tool_call_id,
                        tool_name=name,
                        delta=chunk,
                        is_complete=False
                    )
                
                # Final chunk
                yield ToolResultChunk(
                    tool_call_id=tool_call_id,
                    tool_name=name,
                    delta="",
                    is_complete=True
                )
                
        except Exception as e:
            yield ToolResultChunk(
                tool_call_id=tool_call_id,
                tool_name=name,
                delta=f"Error: {str(e)}",
                is_complete=True
            )
    
    def add_sandbox_tool(self, tool: SandboxTool) -> None:
        """
        Add a sandbox tool.
        
        Args:
            tool: SandboxTool to add
        """
        self._sandbox_tools[tool.name] = tool
        self._tool_source_map[tool.name] = "sandbox"
    
    def get_sandbox_tool(self, name: str) -> Optional[SandboxTool]:
        """
        Get a sandbox tool by name.
        
        Args:
            name: The name of the sandbox tool
        
        Returns:
            The SandboxTool, or None if not found
        """
        return self._sandbox_tools.get(name)
    
    def has_tool(self, name: str) -> bool:
        """Check if a tool exists."""
        return name in self._tool_source_map or name in self._tools or name in self._sandbox_tools
    
    def get_tool_source(self, name: str) -> Optional[str]:
        """Get the source of a tool ('local', 'sandbox', or MCP server name)."""
        return self._tool_source_map.get(name)
