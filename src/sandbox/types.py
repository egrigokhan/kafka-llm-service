"""
Type definitions for the sandbox module.
"""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Configuration for creating or connecting to a sandbox."""
    
    environment_id: str = Field(
        ...,
        description="The environment/template ID to use for the sandbox"
    )
    timeout: int = Field(
        default=300,
        description="Timeout in seconds for sandbox operations"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata for the sandbox"
    )


class SandboxInfo(BaseModel):
    """Information about a sandbox instance."""
    
    id: str = Field(..., description="Unique identifier for the sandbox")
    environment_id: str = Field(..., description="The environment/template ID")
    status: str = Field(..., description="Current status of the sandbox")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    url: Optional[str] = Field(None, description="URL to access the sandbox if applicable")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional sandbox metadata"
    )


class ToolEvent(BaseModel):
    """
    An event from a tool execution in the sandbox.
    Used for streaming tool output.
    """
    
    type: str = Field(
        ...,
        description="Event type: 'output', 'error', 'status', 'complete'"
    )
    data: str = Field(
        default="",
        description="The event data/content"
    )
    tool_name: str = Field(
        ...,
        description="Name of the tool that produced this event"
    )
    is_complete: bool = Field(
        default=False,
        description="Whether this is the final event for this tool execution"
    )
    exit_code: Optional[int] = Field(
        None,
        description="Exit code if the tool execution completed"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event metadata"
    )
