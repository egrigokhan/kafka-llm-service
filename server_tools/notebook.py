"""
Notebook Tools
==============

Tools for executing Python code in a Jupyter-style notebook environment.
Uses SandboxTool for real-time streaming output.
"""

from typing import List

from src.tools import SandboxTool
from src.sandbox import LocalSandbox


class NotebookTools:
    """
    Notebook tool provider that creates notebook tools for a given sandbox.
    
    Unlike the MCP server approach, this uses SandboxTool which streams
    output in real-time through LocalSandbox.run_tool().
    
    Usage:
        notebook_tools = NotebookTools(local_sandbox)
        all_tools = [get_weather_tool] + notebook_tools.tools
    """
    
    def __init__(self, sandbox: LocalSandbox, health_timeout: int = 300):
        """
        Initialize notebook tools with a sandbox instance.
        
        Args:
            sandbox: The LocalSandbox instance to use
            health_timeout: Timeout in seconds for health checks (default 5 min for long runs)
        """
        self.sandbox = sandbox
        self.health_timeout = health_timeout
        self.tools = self._create_tools()
    
    def _create_tools(self) -> List[SandboxTool]:
        """Create the notebook tools."""
        notebook_run_cell = SandboxTool(
            name="notebook_run_cell",
            description=(
                "Execute Python code in a Jupyter-style notebook environment. "
                "The code runs in an IPython kernel with persistent state between calls. "
                "Use this for data analysis, plotting, package installation, and general Python execution. "
                "Output streams in real-time as the code executes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute in the notebook cell"
                    },
                    "description": {
                        "type": "string",
                        "description": "A brief description of what this code does (for logging/display)"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum execution time in seconds (default: 3600)",
                        "default": 3600
                    }
                },
                "required": ["code", "description"]
            },
            sandbox=self.sandbox,
            health_timeout=self.health_timeout
        )
        
        return [notebook_run_cell]


# Legacy MCP server config (deprecated - use NotebookTools instead)
def get_notebook_mcp_server(*args, **kwargs):
    """
    DEPRECATED: Use NotebookTools class instead for streaming support.
    
    This function is kept for backward compatibility but MCP-based notebook
    tools do not support real-time streaming.
    """
    import os
    import warnings
    warnings.warn(
        "get_notebook_mcp_server is deprecated. Use NotebookTools(sandbox) instead for streaming.",
        DeprecationWarning
    )
    
    server_path = kwargs.get("server_path") or os.environ.get(
        "NOTEBOOK_MCP_SERVER_PATH",
        "/Users/gokhan-bb/Documents/kafka-lite-vm/servers/kafka-notebook-mcp-server/main.py"
    )
    exec_dir = kwargs.get("exec_dir") or os.environ.get("EXEC_DIR", "/workspace")
    
    return {
        "name": "notebook",
        "command": "python",
        "args": [server_path],
        "env": {
            "EXEC_DIR": exec_dir,
            **os.environ
        }
    }


NOTEBOOK_MCP_SERVER = None  # Deprecated
