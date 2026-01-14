"""
Lazy Sandbox Wrapper
====================

A sandbox wrapper that defers actual sandbox resolution until a method is called.
This allows the LLM to start immediately without waiting for sandbox creation.
"""

import asyncio
from typing import Any, AsyncGenerator, Dict, Optional, TYPE_CHECKING

from .base import Sandbox, SandboxState, SandboxError
from .types import SandboxConfig, SandboxInfo, ToolEvent

if TYPE_CHECKING:
    from .manager import SandboxManager


class LazySandbox(Sandbox):
    """
    A lazy sandbox that defers actual sandbox resolution until needed.
    
    This allows the agent to start streaming responses immediately,
    and only blocks when a tool actually needs the sandbox.
    
    Usage:
        lazy_sandbox = LazySandbox(thread_id, sandbox_manager)
        # LLM can start immediately
        # When a tool calls run_tool(), it will wait for the real sandbox
    """
    
    def __init__(
        self,
        thread_id: str,
        sandbox_manager: "SandboxManager",
        timeout: float = 60.0
    ):
        """
        Initialize a lazy sandbox.
        
        Args:
            thread_id: The thread ID this sandbox is for
            sandbox_manager: The sandbox manager to get the real sandbox from
            timeout: Timeout in seconds for waiting for the real sandbox
        """
        # Don't call super().__init__ since we don't have a real ID yet
        self._thread_id = thread_id
        self._sandbox_manager = sandbox_manager
        self._timeout = timeout
        self._real_sandbox: Optional[Sandbox] = None
        self._resolving = False
        self._resolve_lock = asyncio.Lock()
    
    @property
    def id(self) -> str:
        """Get the sandbox ID (may be placeholder if not resolved yet)."""
        if self._real_sandbox:
            return self._real_sandbox.id
        return f"pending-{self._thread_id[:8]}"
    
    @property
    def environment_id(self) -> str:
        """Get the environment ID."""
        if self._real_sandbox:
            return self._real_sandbox.environment_id
        return self._sandbox_manager._env_id
    
    @property
    def state(self) -> SandboxState:
        """Get the current sandbox state."""
        if self._real_sandbox:
            return self._real_sandbox.state
        return SandboxState.CREATING
    
    @property
    def is_running(self) -> bool:
        """Check if the sandbox is running."""
        if self._real_sandbox:
            return self._real_sandbox.is_running
        return False
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """Get sandbox metadata."""
        if self._real_sandbox:
            return self._real_sandbox.metadata
        return {"thread_id": self._thread_id, "lazy": True}
    
    async def _ensure_resolved(self) -> Sandbox:
        """
        Ensure we have a real sandbox, waiting if necessary.
        
        This is called before any operation that needs the real sandbox.
        """
        if self._real_sandbox:
            return self._real_sandbox
        
        async with self._resolve_lock:
            # Double-check after acquiring lock
            if self._real_sandbox:
                return self._real_sandbox
            
            print(f"🔄 LazySandbox resolving real sandbox for thread {self._thread_id}")
            
            # Wait for the sandbox to be ready (with timeout)
            start_time = asyncio.get_event_loop().time()
            while True:
                # Check if sandbox is ready in manager cache
                sandbox = await self._sandbox_manager.get_sandbox_if_ready(self._thread_id)
                if sandbox:
                    self._real_sandbox = sandbox
                    print(f"✅ LazySandbox resolved to {sandbox.id} for thread {self._thread_id}")
                    return sandbox
                
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= self._timeout:
                    raise SandboxError(
                        f"Timeout waiting for sandbox for thread {self._thread_id}",
                        sandbox_id=None
                    )
                
                # Wait a bit before checking again
                await asyncio.sleep(0.2)
    
    async def check_health(self) -> bool:
        """Check if sandbox is healthy."""
        sandbox = await self._ensure_resolved()
        return await sandbox.check_health()
    
    async def get_health_status(self) -> Optional[Dict[str, Any]]:
        """Get full health status."""
        sandbox = await self._ensure_resolved()
        return await sandbox.get_health_status()
    
    async def wait_until_live(self, timeout: Optional[float] = None) -> None:
        """Wait until sandbox is live."""
        sandbox = await self._ensure_resolved()
        await sandbox.wait_until_live(timeout)
    
    async def run_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> AsyncGenerator[ToolEvent, None]:
        """Execute a tool - this is where we wait for the real sandbox."""
        sandbox = await self._ensure_resolved()
        async for event in sandbox.run_tool(tool_name, arguments):
            yield event
    
    async def stop(self) -> None:
        """Stop the sandbox."""
        if self._real_sandbox:
            await self._real_sandbox.stop()
    
    async def reset(self) -> None:
        """Reset the sandbox."""
        sandbox = await self._ensure_resolved()
        await sandbox.reset()
    
    async def terminate(self) -> None:
        """Terminate the sandbox."""
        if self._real_sandbox:
            await self._real_sandbox.terminate()
    
    async def get_info(self) -> SandboxInfo:
        """Get sandbox info."""
        sandbox = await self._ensure_resolved()
        return await sandbox.get_info()
    
    async def claim(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Claim the sandbox."""
        sandbox = await self._ensure_resolved()
        return await sandbox.claim(data)
    
    @staticmethod
    async def create(
        environment_id: str,
        config: Optional[SandboxConfig] = None
    ) -> "Sandbox":
        """Not supported for lazy sandbox - use constructor instead."""
        raise NotImplementedError("LazySandbox cannot be created via create()")
    
    @staticmethod
    async def connect(sandbox_id: str, environment_id: Optional[str] = None) -> "Sandbox":
        """Not supported for lazy sandbox - use constructor instead."""
        raise NotImplementedError("LazySandbox cannot be connected via connect()")
    
    @staticmethod
    async def list_sandboxes() -> list["Sandbox"]:
        """Not supported for lazy sandbox."""
        raise NotImplementedError("LazySandbox does not support listing")
    
    def __repr__(self) -> str:
        if self._real_sandbox:
            return f"<LazySandbox resolved={self._real_sandbox.id}>"
        return f"<LazySandbox pending thread={self._thread_id[:8]}>"
