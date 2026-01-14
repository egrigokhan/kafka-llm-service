"""
Sandbox module for managing cloud-based virtual environments.

Sandboxes are VMs in the cloud that agents can claim for themselves,
with their own filesystem, code runtime, browser, etc.
"""

from .base import Sandbox, SandboxError, SandboxState
from .types import SandboxConfig, SandboxInfo, ToolEvent
from .daytona import DaytonaSandbox
from .local import LocalSandbox
from .manager import SandboxManager
from .lazy import LazySandbox

__all__ = [
    "Sandbox",
    "SandboxError",
    "SandboxState",
    "SandboxConfig",
    "SandboxInfo",
    "ToolEvent",
    "DaytonaSandbox",
    "LocalSandbox",
    "SandboxManager",
    "LazySandbox",
]
