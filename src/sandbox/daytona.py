"""
Daytona sandbox implementation.

Uses Daytona's cloud-based sandboxes with a custom tool execution service
running on port 8080 inside the sandbox.
"""

import asyncio
import json
import os
from typing import Any, AsyncGenerator, Dict, Optional

import httpx

from .base import Sandbox, SandboxError, SandboxState
from .types import SandboxConfig, SandboxInfo, ToolEvent

# Lazy import daytona_sdk to avoid import errors if not installed
_daytona_client = None


def _get_daytona_client():
    """Get or create the global Daytona client."""
    global _daytona_client
    if _daytona_client is None:
        try:
            from daytona_sdk import Daytona, DaytonaConfig
            api_key = os.getenv("DAYTONA_API_KEY")
            if not api_key:
                raise SandboxError("DAYTONA_API_KEY environment variable not set", "daytona")
            config = DaytonaConfig(api_key=api_key)
            _daytona_client = Daytona(config)
        except ImportError:
            raise SandboxError("daytona_sdk not installed. Run: pip install daytona-sdk", "daytona")
    return _daytona_client


class DaytonaSandbox(Sandbox):
    """
    Daytona-based sandbox implementation.
    
    Each sandbox runs a service on port 8081 that exposes:
    - GET /health - Health check endpoint
    - POST /run - Tool execution with streaming response
    
    The proxy URL format is: 8081-<sandbox_id>.proxy.daytona.works
    """
    
    PROXY_BASE = "proxy.daytona.works"
    DEFAULT_PORT = 8081
    DEFAULT_TIMEOUT = 300  # 5 minutes
    HEALTH_CHECK_INTERVAL = 2  # seconds between health checks
    
    def __init__(self, sandbox_id: str, environment_id: str):
        """
        Initialize a Daytona sandbox instance.
        
        Args:
            sandbox_id: Unique identifier for this sandbox
            environment_id: The environment/template ID
        """
        super().__init__(sandbox_id, environment_id)
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def base_url(self) -> str:
        """Get the base URL for the sandbox's service."""
        return f"https://{self.DEFAULT_PORT}-{self._id}.{self.PROXY_BASE}"
    
    @property
    def health_url(self) -> str:
        """Get the health check URL."""
        return f"{self.base_url}/health"
    
    @property
    def tool_run_url(self) -> str:
        """Get the tool execution URL."""
        return f"{self.base_url}/run"
    
    @property
    def claim_url(self) -> str:
        """Get the claim URL."""
        return f"{self.base_url}/claim"
    
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
    
    async def check_health(self) -> bool:
        """
        Quick health check to see if sandbox is alive.
        
        Returns:
            True if sandbox is healthy, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                self.health_url,
                timeout=httpx.Timeout(5.0)
            )
            return response.status_code == 200
        except Exception:
            return False
    
    async def get_health_status(self) -> Optional[Dict[str, Any]]:
        """
        Get full health status including claimed state.
        
        Returns:
            Dict with health info including 'healthy' and 'claimed' fields,
            or None if health check fails.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                self.health_url,
                timeout=httpx.Timeout(5.0)
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None
    
    async def wait_until_live(self, timeout: Optional[float] = None) -> None:
        """
        Wait until the sandbox is live and ready to accept commands.
        
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
        log_interval = 5  # Log every 5 seconds
        last_log = 0
        
        print(f"⏳ Waiting for sandbox {self._id} to become healthy (timeout: {timeout}s)...")
        print(f"   Health URL: {self.health_url}")
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            
            # Progress logging
            if elapsed - last_log >= log_interval:
                print(f"   ... still waiting ({elapsed:.0f}s elapsed, last: {last_error or 'connecting'})")
                last_log = elapsed
            
            if elapsed >= timeout:
                self._state = SandboxState.ERROR
                raise TimeoutError(
                    f"Sandbox {self._id} did not become live within {timeout}s. "
                    f"Last error: {last_error}"
                )
            
            try:
                response = await client.get(
                    self.health_url,
                    timeout=httpx.Timeout(10.0)  # Individual request timeout
                )
                
                if response.status_code == 200:
                    self._state = SandboxState.RUNNING
                    print(f"✅ Sandbox {self._id} is healthy! (took {elapsed:.1f}s)")
                    return
                else:
                    last_error = f"HTTP {response.status_code}"
                    
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
            except httpx.TimeoutException as e:
                last_error = f"Request timeout: {e}"
            except Exception as e:
                last_error = f"Unexpected error: {e}"
            
            # Wait before next attempt
            await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
    
    async def run_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> AsyncGenerator[ToolEvent, None]:
        """
        Execute a tool in the sandbox and stream the results.
        
        Makes a POST request to /run with the tool name and arguments,
        and streams the SSE response as ToolEvent objects.
        
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
                    
                    # Handle SSE format: "data: {...}"
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        
                        if data_str == "[DONE]":
                            # Stream complete
                            yield ToolEvent(
                                type="complete",
                                data="",
                                tool_name=tool_name,
                                is_complete=True
                            )
                            return
                        
                        try:
                            data = json.loads(data_str)
                            
                            # Map the response to ToolEvent
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
                                
                        except json.JSONDecodeError as e:
                            # Non-JSON data, treat as raw output
                            yield ToolEvent(
                                type="output",
                                data=data_str,
                                tool_name=tool_name,
                                is_complete=False
                            )
                    
                    elif line.startswith("event: "):
                        # Handle named events if needed
                        pass
                        
        except httpx.ConnectError as e:
            raise SandboxError(f"Failed to connect to sandbox: {e}", self._id)
        except httpx.TimeoutException as e:
            raise SandboxError(f"Tool execution timed out: {e}", self._id)
        except Exception as e:
            if isinstance(e, SandboxError):
                raise
            raise SandboxError(f"Tool execution error: {e}", self._id)
    
    async def stop(self) -> None:
        """
        Stop the sandbox.
        
        Note: Actual stop implementation depends on Daytona API.
        For now, this just updates the local state.
        """
        self._state = SandboxState.STOPPING
        await self._close_client()
        self._state = SandboxState.STOPPED
    
    async def reset(self) -> None:
        """
        Reset the sandbox to its initial state.
        
        Note: Not implemented yet - requires Daytona API integration.
        """
        raise NotImplementedError("Reset not implemented for Daytona sandbox yet")
    
    async def terminate(self) -> None:
        """
        Permanently terminate and destroy the sandbox.
        
        Note: Not implemented yet - requires Daytona API integration.
        """
        await self._close_client()
        self._state = SandboxState.STOPPED
        # TODO: Call Daytona API to terminate the sandbox
    
    async def get_info(self) -> SandboxInfo:
        """
        Get current information about the sandbox.
        
        Returns:
            SandboxInfo: Current sandbox information.
        """
        return SandboxInfo(
            id=self._id,
            environment_id=self._environment_id,
            status=self._state.value,
            url=self.base_url,
            metadata=self._metadata
        )
    
    async def claim(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a claim request to the sandbox.
        
        Posts the given data to the /claim endpoint.
        
        Args:
            data: Dictionary of data to send in the claim request
            
        Returns:
            Dict containing the response from the sandbox
            
        Raises:
            SandboxError: If the claim request fails.
        """
        client = await self._get_client()
        
        try:
            response = await client.post(
                self.claim_url,
                json=data,
                timeout=httpx.Timeout(30.0)
            )
            
            if response.status_code != 200:
                raise SandboxError(
                    f"Claim request failed with status {response.status_code}: {response.text}",
                    self._id
                )
            
            return response.json()
            
        except httpx.ConnectError as e:
            raise SandboxError(f"Failed to connect to sandbox for claim: {e}", self._id)
        except httpx.TimeoutException as e:
            raise SandboxError(f"Claim request timed out: {e}", self._id)
        except Exception as e:
            if isinstance(e, SandboxError):
                raise
            raise SandboxError(f"Claim request error: {e}", self._id)
    
    @staticmethod
    async def create(
        environment_id: str,
        config: Optional[SandboxConfig] = None,
        auto_stop_interval: int = 0,
        env_vars: Optional[Dict[str, str]] = None
    ) -> "DaytonaSandbox":
        """
        Create a new Daytona sandbox instance.
        
        Args:
            environment_id: The environment/snapshot ID to use
            config: Optional configuration for the sandbox
            auto_stop_interval: Auto-stop interval in minutes (0 = disabled)
            env_vars: Optional environment variables for the sandbox
            
        Returns:
            DaytonaSandbox: Connected sandbox instance (call wait_until_live next)
        """
        from daytona_sdk import CreateSandboxFromSnapshotParams
        
        daytona = _get_daytona_client()
        
        try:
            params = CreateSandboxFromSnapshotParams(
                public=True,
                auto_stop_interval=auto_stop_interval,
                snapshot=environment_id
            )
            
            # Create sandbox (blocking call, run in thread)
            new_sandbox = await asyncio.to_thread(daytona.create, params)
            sandbox_id = new_sandbox.id
            
            # Fire-and-forget: run start.sh in background to start services
            startup_cmd = "nohup ./start.sh > /log.txt 2>&1 &"
            envs = env_vars or {}
            asyncio.create_task(
                asyncio.to_thread(new_sandbox.process.exec, startup_cmd, "/", envs)
            )
            
            # Return sandbox wrapper
            sandbox = DaytonaSandbox(sandbox_id, environment_id)
            sandbox._state = SandboxState.STARTING
            return sandbox
            
        except Exception as e:
            raise SandboxError(f"Failed to create Daytona sandbox: {e}", "daytona")
    
    @staticmethod
    async def restart_sandbox(
        sandbox_id: str,
        environment_id: str = "unknown"
    ) -> "DaytonaSandbox":
        """
        Restart a stopped Daytona sandbox.
        
        Args:
            sandbox_id: The ID of the sandbox to restart
            environment_id: The environment ID (for metadata)
            
        Returns:
            DaytonaSandbox: Connected sandbox instance (call wait_until_live next)
        """
        daytona = _get_daytona_client()
        
        try:
            # Get the sandbox
            sandbox = await asyncio.to_thread(daytona.get, sandbox_id)
            
            # Start the sandbox (if stopped)
            sandbox_state = getattr(sandbox, 'state', None)
            if sandbox_state != 'started':
                await asyncio.to_thread(sandbox.start)
            
            # Run start.sh to restart services
            startup_cmd = "nohup ./start.sh > /log.txt 2>&1 &"
            await asyncio.to_thread(sandbox.process.exec, startup_cmd, "/")
            
            # Return sandbox wrapper
            result = DaytonaSandbox(sandbox_id, environment_id)
            result._state = SandboxState.STARTING
            return result
            
        except Exception as e:
            raise SandboxError(f"Failed to restart Daytona sandbox {sandbox_id}: {e}", sandbox_id)
    
    @staticmethod
    async def connect(sandbox_id: str, environment_id: str = "unknown") -> "DaytonaSandbox":
        """
        Connect to an existing Daytona sandbox by ID.
        
        Args:
            sandbox_id: The ID of the sandbox to connect to
            environment_id: The environment ID (optional, defaults to "unknown")
            
        Returns:
            DaytonaSandbox: Connected sandbox instance
        """
        sandbox = DaytonaSandbox(sandbox_id, environment_id)
        sandbox._state = SandboxState.RUNNING  # Assume it's running until we check
        return sandbox
    
    @staticmethod
    async def get_sandbox_info(sandbox_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a Daytona sandbox.
        
        Args:
            sandbox_id: The ID of the sandbox
            
        Returns:
            Dict with sandbox info, or None if not found
        """
        daytona = _get_daytona_client()
        
        try:
            sandbox = await asyncio.to_thread(daytona.get, sandbox_id)
            return {
                "id": sandbox.id,
                "state": getattr(sandbox, 'state', None),
                "auto_stop_interval": getattr(sandbox, 'auto_stop_interval', None),
            }
        except Exception:
            return None
    
    @staticmethod
    async def stop_sandbox(sandbox_id: str) -> bool:
        """
        Stop a running Daytona sandbox.
        
        Args:
            sandbox_id: The ID of the sandbox to stop
            
        Returns:
            True if stopped successfully, False otherwise
        """
        daytona = _get_daytona_client()
        
        try:
            sandbox = await asyncio.to_thread(daytona.get, sandbox_id)
            await asyncio.to_thread(sandbox.stop)
            return True
        except Exception:
            return False
    
    @staticmethod
    async def delete_sandbox(sandbox_id: str) -> bool:
        """
        Delete a Daytona sandbox.
        
        Args:
            sandbox_id: The ID of the sandbox to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        daytona = _get_daytona_client()
        
        try:
            sandbox = await asyncio.to_thread(daytona.get, sandbox_id)
            await asyncio.to_thread(sandbox.delete)
            return True
        except Exception:
            return False
    
    @staticmethod
    async def list_sandboxes() -> list["DaytonaSandbox"]:
        """
        List all available Daytona sandboxes.
        
        Note: Not implemented yet - requires Daytona API integration.
        """
        raise NotImplementedError("List not implemented for Daytona sandbox yet")
    
    async def __aenter__(self) -> "DaytonaSandbox":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self._close_client()
