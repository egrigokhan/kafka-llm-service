"""
Kafka V1 Provider
=================

Version 1 implementation of the Kafka agent.
"""

import os
import logging
from typing import Optional, List, Dict, Any, AsyncGenerator

from src.llm import PortkeyLLMProvider, Message, SummarizationCompactionProvider
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
        If a thread_id is set, fetches the instruction_prompt from the kafka_profile
        and appends it to the prompt provider.
        """
        if self._initialized:
            return
        
        # Use external db client if provided, otherwise create Supabase client
        if self._external_db_client:
            self._db_client = self._external_db_client
        else:
            self._db_client = SupabaseClient()
        
        # Fetch thread config including global_prompt and provider-specific virtual keys
        global_prompt: str | None = None
        kafka_profile_id: str | None = None
        playbooks: List[Dict[str, Any]] = []
        virtual_keys: Dict[str, str | None] = {
            "openai": None,
            "anthropic": None,
            "google": None,
            "bedrock": None,
        }
        
        if self._thread_id and self._db_client:
            try:
                thread_config = await self._db_client.get_thread_config(self._thread_id)
                if thread_config:
                    global_prompt = thread_config.get("global_prompt")
                    kafka_profile_id = thread_config.get("kafka_profile_id")
                    virtual_keys["openai"] = thread_config.get("openai_pk_virtual_key")
                    virtual_keys["anthropic"] = thread_config.get("anthropic_pk_virtual_key")
                    virtual_keys["google"] = thread_config.get("gemini_pk_virtual_key")
                    virtual_keys["bedrock"] = thread_config.get("bedrock_pk_virtual_key")
                    
                    print(f"🔍 Thread config for {self._thread_id[:8]}:")
                    print(f"   openai_vk: {virtual_keys['openai'][:15] if virtual_keys['openai'] else None}...")
                    print(f"   anthropic_vk: {virtual_keys['anthropic'][:15] if virtual_keys['anthropic'] else None}...")
                    print(f"   google_vk: {virtual_keys['google'][:15] if virtual_keys['google'] else None}...")
                    
                    if global_prompt:
                        print(f"📋 Loaded global_prompt for thread {self._thread_id[:8]}...")
                    
                    # Fetch playbooks for this kafka profile
                    if kafka_profile_id:
                        playbooks = await self._db_client.get_playbooks_for_kafka_profile(kafka_profile_id)
                        if playbooks:
                            print(f"📚 Loaded {len(playbooks)} playbooks for kafka profile")
            except Exception as e:
                print(f"⚠️ Failed to fetch thread config: {e}")
        
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
        
        # Initialize LLM provider with tools and provider-specific virtual keys from profile
        # The provider will select the correct virtual key based on the model being used
        self._llm_provider = PortkeyLLMProvider(
            model=self._default_model,
            tool_provider=self._tool_provider,
            virtual_keys=virtual_keys
        )
        
        # Create a separate client for context compaction (uses same virtual keys)
        # This avoids issues with the compaction provider needing to make LLM calls
        self._compaction_llm_client = self._llm_provider._create_client_for_provider("openai")
        
        # Initialize context compaction provider for handling long conversations
        logger = logging.getLogger("kafka.v1.compaction")
        self._context_compaction_provider = SummarizationCompactionProvider(
            llm_client=self._compaction_llm_client,
            summarize_ratio=0.75,
            min_messages_to_summarize=10,
            logger=logger,
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
        
        # Add global_prompt from kafka_profile as the last section
        if global_prompt and self._prompt_provider:
            self._prompt_provider.add_section(
                name="custom_instructions",
                content=global_prompt,
                order=999  # Ensure it's at the end
            )
            print(f"📝 Added custom_instructions section to prompt")
        
        # Add available playbooks as a markdown table at the end of the system prompt
        if playbooks and self._prompt_provider:
            playbooks_content = self._format_playbooks_table(playbooks)
            self._prompt_provider.add_section(
                name="available_playbooks",
                content=playbooks_content,
                order=1000  # After custom_instructions
            )
            print(f"📚 Added available_playbooks section to prompt ({len(playbooks)} playbooks)")
        
        # Initialize agent with prompt provider (or system prompt string as fallback)
        self._agent = Agent(
            llm_provider=self._llm_provider,
            tool_provider=self._tool_provider,
            system_prompt=self._system_prompt,  # Takes precedence if set
            prompt_provider=self._prompt_provider,  # Used if system_prompt is None
            context_compaction_provider=self._context_compaction_provider,
            logger=logging.getLogger("kafka.v1.agent"),
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
    
    def _format_playbooks_table(self, playbooks: List[Dict[str, Any]]) -> str:
        """
        Format playbooks as a markdown table for injection into the system prompt.
        
        Args:
            playbooks: List of playbook dicts with id, name, description
            
        Returns:
            Markdown formatted string with playbooks table
        """
        if not playbooks:
            return ""
        
        lines = [
            "## Available Playbooks",
            "",
            "The following playbooks are available for this profile. Use them when the task matches their description:",
            "",
            "| ID | Title | When to Use |",
            "|---|---|---|",
        ]
        
        for pb in playbooks:
            pb_id = pb.get("id", "")
            name = pb.get("name", "").replace("|", "\\|")  # Escape pipes
            description = pb.get("description", "").replace("|", "\\|").replace("\n", " ")  # Escape and flatten
            lines.append(f"| {pb_id} | {name} | {description} |")
        
        return "\n".join(lines)