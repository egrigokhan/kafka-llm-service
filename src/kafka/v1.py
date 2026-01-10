"""
Kafka V1 Provider
=================

Version 1 implementation of the Kafka agent.
"""

import os
from typing import Optional, List, Dict, Any, AsyncGenerator

from src.llm import PortkeyLLMProvider, Message
from src.db import SupabaseClient
from src.tools import AgentToolProvider, Tool, SandboxTool
from src.agents import Agent

from .base import KafkaAgent


class KafkaV1Provider(KafkaAgent):
    """
    Kafka V1 agent provider.
    
    This is the first version of the Kafka agent, featuring:
    - Portkey LLM provider
    - Supabase thread storage
    - Local tools, MCP tools, and sandbox tools
    - Agentic loop with idle termination
    
    Usage:
        async with KafkaV1Provider(thread_id="my-thread") as kafka:
            async for event in kafka.run_with_thread(
                new_messages=[Message(role="user", content="Hello")],
                model="gpt-4o"
            ):
                print(event)
    """
    
    DEFAULT_SYSTEM_PROMPT = (
        "You are a helpful assistant. IMPORTANT: You MUST always call the 'idle' "
        "function when you are done responding. Even if you just want to say something "
        "without using tools, you must still call 'idle' afterwards to signal completion. "
        "Never end your turn without calling 'idle'."
    )
    
    def __init__(
        self,
        thread_id: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        sandbox_tools: Optional[List[SandboxTool]] = None,
        mcp_servers: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        default_model: Optional[str] = None
    ):
        """
        Initialize the Kafka V1 provider.
        
        Args:
            thread_id: Optional thread ID for persistent conversations
            tools: List of local Tool objects
            sandbox_tools: List of SandboxTool objects
            mcp_servers: List of MCP server configurations
            system_prompt: Custom system prompt for the agent
            default_model: Default model to use
        """
        super().__init__(thread_id)
        
        self._tools = tools or []
        self._sandbox_tools = sandbox_tools or []
        self._mcp_servers = mcp_servers or []
        self._system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self._default_model = default_model or os.environ.get("DEFAULT_MODEL", "gpt-4o")
        
        self._llm_provider: Optional[PortkeyLLMProvider] = None
    
    @property
    def llm_provider(self) -> Optional[PortkeyLLMProvider]:
        """Get the LLM provider."""
        return self._llm_provider
    
    async def initialize(self) -> None:
        """
        Initialize the Kafka V1 provider.
        
        Sets up database, tools, LLM provider, and agent.
        """
        if self._initialized:
            return
        
        # Initialize database client
        self._db_client = SupabaseClient()
        
        # Initialize tool provider
        self._tool_provider = AgentToolProvider(
            tools=self._tools,
            mcp_servers=self._mcp_servers,
            sandbox_tools=self._sandbox_tools
        )
        await self._tool_provider.connect()
        
        # Initialize LLM provider with tools
        self._llm_provider = PortkeyLLMProvider(
            model=self._default_model,
            tool_provider=self._tool_provider
        )
        
        # Initialize agent
        self._agent = Agent(
            llm_provider=self._llm_provider,
            tool_provider=self._tool_provider,
            system_prompt=self._system_prompt
        )
        
        self._initialized = True
        
        # Log available tools
        all_tools = await self.get_tools()
        tool_names = [t["function"]["name"] for t in all_tools]
        print(f"✅ KafkaV1 initialized with {len(tool_names)} tools: {tool_names}")
    
    async def cleanup(self) -> None:
        """
        Clean up resources.
        """
        if self._tool_provider:
            await self._tool_provider.disconnect()
        
        if self._llm_provider:
            await self._llm_provider.close()
        
        self._initialized = False
        print("👋 KafkaV1 cleaned up")
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        """
        Get all available tools.
        
        Returns:
            List of tool definitions in OpenAI format.
        """
        if not self._tool_provider:
            return []
        
        return await self._tool_provider.get_tools()
    
    async def run(
        self,
        messages: List[Message],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent with the given messages.
        
        Yields events as they occur.
        
        Args:
            messages: Input messages
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Yields:
            Event dictionaries
        """
        if not self._agent:
            raise RuntimeError("KafkaV1 not initialized. Call initialize() first.")
        
        async for event in self._agent.run(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            yield event
    
    def add_tool(self, tool: Tool) -> None:
        """
        Add a tool to the provider.
        
        Note: Must be called before initialize().
        """
        self._tools.append(tool)
        if self._tool_provider:
            self._tool_provider.add_tool(tool)
    
    def add_sandbox_tool(self, tool: SandboxTool) -> None:
        """
        Add a sandbox tool to the provider.
        
        Note: Must be called before initialize().
        """
        self._sandbox_tools.append(tool)
        if self._tool_provider:
            self._tool_provider.add_sandbox_tool(tool)
    
    def add_mcp_server(self, server: Dict[str, Any]) -> None:
        """
        Add an MCP server configuration.
        
        Note: Must be called before initialize().
        """
        self._mcp_servers.append(server)
