"""
Kafka V1 Provider
=================

Version 1 implementation of the Kafka agent.
"""

import os
from typing import Optional, List, Dict, Any, AsyncGenerator

from src.llm import PortkeyLLMProvider, Message
from src.db import SupabaseClient, LocalDBClient
from src.tools import AgentToolProvider, Tool, SandboxTool
from src.agents import Agent
from src.prompts import PromptProviderV1, PromptProvider

from .base import KafkaAgent

# Type alias for any DB client that supports our interface
DBClient = SupabaseClient | LocalDBClient


class KafkaV1Provider(KafkaAgent):
    """
    Kafka V1 agent provider.
    
    This is the first version of the Kafka agent, featuring:
    - Portkey LLM provider
    - Supabase thread storage
    - Local tools, MCP tools, and sandbox tools
    - Agentic loop with idle termination
    - PromptProviderV1 for system prompt generation
    
    Usage:
        async with KafkaV1Provider(thread_id="my-thread") as kafka:
            async for event in kafka.run_with_thread(
                new_messages=[Message(role="user", content="Hello")],
                model="gpt-4o"
            ):
                print(event)
    """
    
    DEFAULT_SYSTEM_PROMPT = (
        "You are a helpful assistant. "
        "When using tools, call the 'idle' function when you are done to signal completion. "
        "For simple responses without tools, just respond naturally."
    )
    
    def __init__(
        self,
        thread_id: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        sandbox_tools: Optional[List[SandboxTool]] = None,
        mcp_servers: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        prompt_provider: Optional[PromptProvider] = None,
        prompt_sections: Optional[List[str]] = None,
        prompt_enrichment: Optional[Dict[str, Any]] = None,
        default_model: Optional[str] = None,
        db_client: Optional[DBClient] = None,
        tool_provider: Optional[AgentToolProvider] = None
    ):
        """
        Initialize the Kafka V1 provider.
        
        Args:
            thread_id: Optional thread ID for persistent conversations
            tools: List of local Tool objects
            sandbox_tools: List of SandboxTool objects
            mcp_servers: List of MCP server configurations
            system_prompt: Custom system prompt (overrides prompt_provider)
            prompt_provider: Custom PromptProvider instance (overrides default)
            prompt_sections: Sections to include in default prompt provider
            prompt_enrichment: Additional enrichment data for prompt templates
            default_model: Default model to use
            db_client: Database client for thread storage (LocalDBClient or SupabaseClient)
            tool_provider: Optional shared tool provider (avoids MCP reconnection issues)
        """
        super().__init__(thread_id)
        
        self._tools = tools or []
        self._sandbox_tools = sandbox_tools or []
        self._mcp_servers = mcp_servers or []
        self._system_prompt = system_prompt  # May be None - will use prompt_provider
        self._external_prompt_provider = prompt_provider
        self._prompt_sections = prompt_sections
        self._prompt_enrichment = prompt_enrichment or {}
        self._default_model = default_model or os.environ.get("DEFAULT_MODEL", "gpt-4o")
        self._external_db_client = db_client
        self._shared_tool_provider = tool_provider
        
        self._prompt_provider: Optional[PromptProvider] = None
        self._llm_provider: Optional[PortkeyLLMProvider] = None
        self._owns_tool_provider = False  # Track if we own the tool provider (for cleanup)
    
    @property
    def llm_provider(self) -> Optional[PortkeyLLMProvider]:
        """Get the LLM provider."""
        return self._llm_provider
    
    @property
    def prompt_provider(self) -> Optional[PromptProvider]:
        """Get the prompt provider."""
        return self._prompt_provider
    
    async def initialize(self) -> None:
        """
        Initialize the Kafka V1 provider.
        
        Sets up database, tools, LLM provider, prompt provider, and agent.
        """
        if self._initialized:
            return
        
        # Use external db client if provided, otherwise create Supabase client
        if self._external_db_client:
            self._db_client = self._external_db_client
        else:
            self._db_client = SupabaseClient()
        
        # Use shared tool provider if provided, otherwise create new one
        if self._shared_tool_provider:
            self._tool_provider = self._shared_tool_provider
            self._owns_tool_provider = False
        else:
            self._tool_provider = AgentToolProvider(
                tools=self._tools,
                mcp_servers=self._mcp_servers,
                sandbox_tools=self._sandbox_tools
            )
            await self._tool_provider.connect()
            self._owns_tool_provider = True
        
        # Initialize LLM provider with tools
        self._llm_provider = PortkeyLLMProvider(
            model=self._default_model,
            tool_provider=self._tool_provider
        )
        
        # Initialize prompt provider
        # Priority: external prompt_provider > system_prompt string > default PromptProviderV1
        if self._external_prompt_provider:
            self._prompt_provider = self._external_prompt_provider
        elif self._system_prompt is None:
            # Create default PromptProviderV1 with optional section filtering
            self._prompt_provider = PromptProviderV1(sections=self._prompt_sections)
            # Apply any additional enrichment
            if self._prompt_enrichment:
                self._prompt_provider.enrich(self._prompt_enrichment)
        # If system_prompt is set, _prompt_provider stays None and we pass string directly
        
        # Initialize agent with prompt provider (or system prompt string as fallback)
        self._agent = Agent(
            llm_provider=self._llm_provider,
            tool_provider=self._tool_provider,
            system_prompt=self._system_prompt,  # Takes precedence if set
            prompt_provider=self._prompt_provider  # Used if system_prompt is None
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
        # Only disconnect tool provider if we own it (not shared)
        if self._tool_provider and self._owns_tool_provider:
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
