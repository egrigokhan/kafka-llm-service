"""
Local Sandbox implementation.

Connects directly to a local or remote sandbox service via URL.
The URL is the base endpoint for /health, /tool/run, etc.
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional

import httpx

from .base import Sandbox, SandboxError, SandboxState
from .types import SandboxConfig, SandboxInfo, ToolEvent


class LocalSandbox(Sandbox):
    """
    Local sandbox that connects directly to a URL.
    
    Unlike DaytonaSandbox which constructs URLs from a sandbox ID,
    LocalSandbox takes a base URL directly. This is useful for:
    - Local development with a sandbox running on localhost
    - Direct connection to a known sandbox endpoint
    - Custom sandbox deployments
    
    The sandbox service should expose:
    - GET /health - Health check endpoint
    - POST /tool/run - Tool execution with streaming response
    
    Usage:
        sandbox = LocalSandbox("http://localhost:8080")
        await sandbox.wait_until_live()
        
        async for event in sandbox.run_tool("run_code", {"code": "print('hello')"}):
            print(event.data)
    """
    
    DEFAULT_TIMEOUT = 300  # 5 minutes
    HEALTH_CHECK_INTERVAL = 2  # seconds between health checks
    
    def __init__(self, base_url: str, environment_id: str = "local"):
        """
        Initialize a local sandbox instance.
        
        Args:
            base_url: The base URL for the sandbox service (e.g., "http://localhost:8080")
            environment_id: Optional environment identifier (defaults to "local")
        """
        # Use the base_url as the sandbox ID for identification
        super().__init__(sandbox_id=base_url, environment_id=environment_id)
        self._base_url = base_url.rstrip("/")  # Remove trailing slash
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def base_url(self) -> str:
        """Get the base URL for the sandbox service."""
        return self._base_url
    
    @property
    def health_url(self) -> str:
        """Get the health check URL."""
        return f"{self._base_url}/health"
    
    @property
    def tool_run_url(self) -> str:
        """Get the tool execution URL."""
        return f"{self._base_url}/run"
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.DEFAULT_TIMEOUT))
        return self._client
    
    async def _close_client(self) -> None:
        """Close the HTTP client if open."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def wait_until_live(self, timeout: Optional[float] = None) -> None:
        """
        Wait until the sandbox is live and ready.
        
        Polls the health endpoint until it returns 200 OK.
        
        Args:
            timeout: Maximum time to wait in seconds. Defaults to DEFAULT_TIMEOUT.
            
        Raises:
            SandboxError: If the sandbox fails to become live.
            TimeoutError: If the timeout is exceeded.
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        self._state = SandboxState.STARTING
        
        client = await self._get_client()
        start_time = asyncio.get_event_loop().time()
        last_error: Optional[str] = None
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                self._state = SandboxState.ERROR
                raise TimeoutError(
                    f"Sandbox at {self._base_url} did not become live within {timeout}s. "
                    f"Last error: {last_error}"
                )
            
            try:
                response = await client.get(
                    self.health_url,
                    timeout=httpx.Timeout(10.0)
                )
                
                if response.status_code == 200:
                    self._state = SandboxState.RUNNING
                    return
                else:
                    last_error = f"Health check returned {response.status_code}"
                    
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
            except httpx.TimeoutException as e:
                last_error = f"Request timeout: {e}"
            except Exception as e:
                last_error = f"Unexpected error: {e}"
            
            await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
    
    async def run_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> AsyncGenerator[ToolEvent, None]:
        """
        Execute a tool in the sandbox and stream the results.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool
            
        Yields:
            ToolEvent: Events from the tool execution
            
        Raises:
            SandboxError: If the tool execution fails.
        """
        if self._state != SandboxState.RUNNING:
            raise SandboxError(
                f"Sandbox is not running (state: {self._state.value})",
                self._id
            )
        
        client = await self._get_client()
        
        payload = {
            "tool_name": tool_name,
            "arguments": arguments
        }
        
        try:
            async with client.stream(
                "POST",
                self.tool_run_url,
                json=payload,
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(self.DEFAULT_TIMEOUT)
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise SandboxError(
                        f"Tool execution failed with status {response.status_code}: {error_text.decode()}",
                        self._id
                    )
                
                # Parse SSE stream
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    if line.startswith("data: "):
                        data_str = line[6:]
                        
                        if data_str == "[DONE]":
                            yield ToolEvent(
                                type="complete",
                                data="",
                                tool_name=tool_name,
                                is_complete=True
                            )
                            return
                        
                        try:
                            data = json.loads(data_str)
                            
                            event_type = data.get("type", "output")
                            event_data = data.get("data", data.get("content", ""))
                            is_complete = data.get("is_complete", False)
                            exit_code = data.get("exit_code")
                            metadata = data.get("metadata", {})
                            
                            yield ToolEvent(
                                type=event_type,
                                data=str(event_data),
                                tool_name=tool_name,
                                is_complete=is_complete,
                                exit_code=exit_code,
                                metadata=metadata
                            )
                            
                            if is_complete:
                                return
                                
                        except json.JSONDecodeError:
                            yield ToolEvent(
                                type="output",
                                data=data_str,
                                tool_name=tool_name,
                                is_complete=False
                            )
                        
        except httpx.ConnectError as e:
            raise SandboxError(f"Failed to connect to sandbox: {e}", self._id)
        except httpx.TimeoutException as e:
            raise SandboxError(f"Tool execution timed out: {e}", self._id)
        except Exception as e:
            if isinstance(e, SandboxError):
                raise
            raise SandboxError(f"Tool execution error: {e}", self._id)
    
    async def stop(self) -> None:
        """Stop the sandbox (closes client connection)."""
        self._state = SandboxState.STOPPING
        await self._close_client()
        self._state = SandboxState.STOPPED
    
    async def reset(self) -> None:
        """Reset not supported for local sandbox."""
        raise NotImplementedError("Reset not supported for local sandbox")
    
    async def terminate(self) -> None:
        """Terminate the sandbox (closes client connection)."""
        await self._close_client()
        self._state = SandboxState.STOPPED
    
    async def get_info(self) -> SandboxInfo:
        """Get current sandbox information."""
        return SandboxInfo(
            id=self._id,
            environment_id=self._environment_id,
            status=self._state.value,
            url=self._base_url,
            metadata=self._metadata
        )
    
    @staticmethod
    async def create(
        environment_id: str,
        config: Optional[SandboxConfig] = None
    ) -> "LocalSandbox":
        """Create not supported - use connect() instead."""
        raise NotImplementedError("Use LocalSandbox(url) or LocalSandbox.connect(url) instead")
    
    @staticmethod
    async def connect(url: str, environment_id: str = "local") -> "LocalSandbox":
        """
        Connect to a local sandbox at the given URL.
        
        Args:
            url: The base URL for the sandbox service
            environment_id: Optional environment identifier
            
        Returns:
            LocalSandbox: Connected sandbox instance
        """
        sandbox = LocalSandbox(url, environment_id)
        sandbox._state = SandboxState.RUNNING  # Assume running until health check
        return sandbox
    
    @staticmethod
    async def list_sandboxes() -> list["LocalSandbox"]:
        """List not supported for local sandbox."""
        raise NotImplementedError("List not supported for local sandbox")
    
    async def __aenter__(self) -> "LocalSandbox":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self._close_client()
