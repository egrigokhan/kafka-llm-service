"""
Base class for sandbox implementations.

A Sandbox represents a cloud-based virtual environment that an agent can use
for executing code, running tools, browsing the web, and managing files.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncGenerator, Dict, Optional

from .types import SandboxConfig, SandboxInfo, ToolEvent


class SandboxState(Enum):
    """Possible states of a sandbox."""
    
    CREATING = "creating"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class SandboxError(Exception):
    """Exception raised for sandbox-related errors."""
    
    def __init__(self, message: str, sandbox_id: Optional[str] = None):
        self.message = message
        self.sandbox_id = sandbox_id
        super().__init__(self.message)
    
    def __str__(self) -> str:
        if self.sandbox_id:
            return f"[Sandbox {self.sandbox_id}] {self.message}"
        return self.message


class Sandbox(ABC):
    """
    Abstract base class for sandbox implementations.
    
    A sandbox is a cloud-based VM that provides:
    - Isolated filesystem
    - Code execution runtime
    - Browser automation
    - Tool execution with streaming output
    
    Subclasses should implement the abstract methods to integrate
    with specific sandbox providers (e.g., E2B, Modal, etc.).
    """
    
    def __init__(self, sandbox_id: str, environment_id: str):
        """
        Initialize a sandbox instance.
        
        Args:
            sandbox_id: Unique identifier for this sandbox instance
            environment_id: The environment/template ID used to create the sandbox
        """
        self._id = sandbox_id
        self._environment_id = environment_id
        self._state = SandboxState.CREATING
        self._metadata: Dict[str, Any] = {}
    
    @property
    def id(self) -> str:
        """Get the sandbox ID."""
        return self._id
    
    @property
    def environment_id(self) -> str:
        """Get the environment ID."""
        return self._environment_id
    
    @property
    def state(self) -> SandboxState:
        """Get the current sandbox state."""
        return self._state
    
    @property
    def is_running(self) -> bool:
        """Check if the sandbox is running."""
        return self._state == SandboxState.RUNNING
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """Get sandbox metadata."""
        return self._metadata
    
    @abstractmethod
    async def wait_until_live(self, timeout: Optional[float] = None) -> None:
        """
        Wait until the sandbox is live and ready to accept commands.
        
        Args:
            timeout: Maximum time to wait in seconds. None means use default.
            
        Raises:
            SandboxError: If the sandbox fails to become live within timeout.
            TimeoutError: If the timeout is exceeded.
        """
        pass
    
    @abstractmethod
    async def run_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> AsyncGenerator[ToolEvent, None]:
        """
        Execute a tool in the sandbox and stream the results.
        
        Args:
            tool_name: Name of the tool to execute (e.g., "run_code", "browser", "file_read")
            arguments: Arguments to pass to the tool
            
        Yields:
            ToolEvent: Events from the tool execution (output, errors, completion)
            
        Raises:
            SandboxError: If the tool execution fails.
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the sandbox.
        
        The sandbox can be restarted after stopping.
        
        Raises:
            SandboxError: If stopping fails.
        """
        pass
    
    @abstractmethod
    async def reset(self) -> None:
        """
        Reset the sandbox to its initial state.
        
        This clears any changes made to the filesystem, running processes, etc.
        
        Raises:
            SandboxError: If reset fails.
        """
        pass
    
    @abstractmethod
    async def terminate(self) -> None:
        """
        Permanently terminate and destroy the sandbox.
        
        After termination, the sandbox cannot be restarted.
        
        Raises:
            SandboxError: If termination fails.
        """
        pass
    
    @abstractmethod
    async def get_info(self) -> SandboxInfo:
        """
        Get current information about the sandbox.
        
        Returns:
            SandboxInfo: Current sandbox information.
        """
        pass
    
    @staticmethod
    @abstractmethod
    async def create(
        environment_id: str,
        config: Optional[SandboxConfig] = None
    ) -> "Sandbox":
        """
        Create a new sandbox instance.
        
        This is a factory method that creates and initializes a new sandbox.
        
        Args:
            environment_id: The environment/template ID to use
            config: Optional configuration for the sandbox
            
        Returns:
            Sandbox: A new sandbox instance (not yet live, call wait_until_live)
            
        Raises:
            SandboxError: If sandbox creation fails.
        """
        pass
    
    @staticmethod
    @abstractmethod
    async def connect(sandbox_id: str) -> "Sandbox":
        """
        Connect to an existing sandbox by ID.
        
        Args:
            sandbox_id: The ID of the sandbox to connect to
            
        Returns:
            Sandbox: Connected sandbox instance
            
        Raises:
            SandboxError: If connection fails or sandbox doesn't exist.
        """
        pass
    
    @staticmethod
    @abstractmethod
    async def list_sandboxes() -> list["Sandbox"]:
        """
        List all available sandboxes.
        
        Returns:
            List of sandbox instances.
        """
        pass
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self._id} env={self._environment_id} state={self._state.value}>"
