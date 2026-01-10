"""
Shell Tools
=============

Tools for creating and executing commands in sandbox shell sessions.
"""

from typing import List

from src.tools import SandboxTool
from src.sandbox import LocalSandbox


class ShellTools:
    """
    Shell tool provider that creates shell tools for a given sandbox.
    
    Usage:
        shell_tools = ShellTools(local_sandbox)
        all_tools = [get_weather_tool, count_tool] + shell_tools.tools
    """
    
    def __init__(self, sandbox: LocalSandbox, health_timeout: int = 30):
        """
        Initialize shell tools with a sandbox instance.
        
        Args:
            sandbox: The LocalSandbox instance to use
            health_timeout: Timeout in seconds for health checks
        """
        self.sandbox = sandbox
        self.health_timeout = health_timeout
        self.tools = self._create_tools()
    
    def _create_tools(self) -> List[SandboxTool]:
        """Create the shell tools."""
        create_shell_tool = SandboxTool(
            name="create_shell",
            description="Create a new shell session in the sandbox. You must create a shell before running commands.",
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "A unique identifier for the shell session (e.g., 'main', 'worker1')"
                    }
                },
                "required": ["shell_id"]
            },
            sandbox=self.sandbox,
            health_timeout=self.health_timeout
        )
        
        shell_exec_tool = SandboxTool(
            name="shell_exec",
            description="Execute a shell command in an existing shell session. Returns the command output.",
            parameters={
                "type": "object",
                "properties": {
                    "shell_id": {
                        "type": "string",
                        "description": "The shell session ID to run the command in"
                    },
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute (e.g., 'ls -la', 'cat file.txt', 'python script.py')"
                    }
                },
                "required": ["shell_id", "command"]
            },
            sandbox=self.sandbox,
            health_timeout=self.health_timeout
        )
        
        return [create_shell_tool, shell_exec_tool]
