"""
Kafka Agent Base Class
======================

Abstract base class for Kafka agents.
Kafka is the name of our overall agent system.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncGenerator, Union

from src.llm import Message, CompletionResponse
from src.db import SupabaseClient
from src.tools import AgentToolProvider, ToolResultChunk
from src.agents import Agent

from .types import ChatCompletionRequest, AgentRunRequest
from .utils import sanitize_messages_for_openai


class KafkaAgent(ABC):
    """
    Abstract base class for Kafka agents.
    
    A Kafka agent manages conversation threads, tool execution,
    and LLM interactions. It provides a high-level interface
    for running agent loops with automatic message persistence.
    
    Subclasses must implement the abstract methods to define
    specific agent behavior and tool configurations.
    """
    
    def __init__(self, thread_id: Optional[str] = None):
        """
        Initialize the Kafka agent.
        
        Args:
            thread_id: Optional thread ID for persistent conversations.
                      If None, operates in stateless mode.
        """
        self._thread_id = thread_id
        self._db_client: Optional[SupabaseClient] = None
        self._tool_provider: Optional[AgentToolProvider] = None
        self._agent: Optional[Agent] = None
        self._initialized = False
    
    @property
    def thread_id(self) -> Optional[str]:
        """Get the thread ID."""
        return self._thread_id
    
    @property
    def is_initialized(self) -> bool:
        """Check if the agent is initialized."""
        return self._initialized
    
    @property
    def tool_provider(self) -> Optional[AgentToolProvider]:
        """Get the tool provider."""
        return self._tool_provider
    
    @property
    def agent(self) -> Optional[Agent]:
        """Get the underlying agent."""
        return self._agent
    
    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the agent.
        
        This should set up:
        - Database client (if using threads)
        - Tool provider with tools
        - LLM provider
        - Agent instance
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        Clean up resources.
        
        Should disconnect tool providers, close LLM connections, etc.
        """
        pass
    
    @abstractmethod
    async def get_tools(self) -> List[Dict[str, Any]]:
        """
        Get all available tools.
        
        Returns:
            List of tool definitions in OpenAI format.
        """
        pass
    
    async def get_thread_messages(self) -> List[Message]:
        """
        Get messages from the current thread.
        
        Returns:
            List of messages from the thread, or empty list if no thread.
        """
        if not self._thread_id or not self._db_client:
            return []
        
        return await self._db_client.get_thread_messages(self._thread_id)
    
    async def ensure_thread_exists(self) -> None:
        """
        Ensure the thread exists, creating it if necessary.
        """
        if not self._thread_id or not self._db_client:
            return
        
        exists = await self._db_client.thread_exists(self._thread_id)
        if not exists:
            await self._db_client.create_thread(thread_id=self._thread_id)
    
    async def save_message(self, message: Message) -> None:
        """
        Save a message to the current thread.
        
        Args:
            message: The message to save.
        """
        if not self._thread_id or not self._db_client:
            return
        
        await self._db_client.add_message(self._thread_id, message)
    
    async def save_messages(self, messages: List[Message]) -> None:
        """
        Save multiple messages to the current thread.
        
        Args:
            messages: The messages to save.
        """
        for msg in messages:
            await self.save_message(msg)
    
    @abstractmethod
    async def run(
        self,
        messages: List[Message],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent with the given messages.
        
        Yields events as they occur (LLM chunks, tool calls, tool results, done).
        
        Args:
            messages: Input messages (history + new)
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Yields:
            Event dictionaries (OpenAI-compatible format)
        """
        pass
    
    async def run_with_thread(
        self,
        new_messages: List[Message],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        save_to_thread: bool = True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent with thread history.
        
        Retrieves history from thread, appends new messages,
        runs the agent, and optionally saves results.
        
        Args:
            new_messages: New messages to add
            model: Model ID to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            save_to_thread: Whether to save messages to thread
            
        Yields:
            Event dictionaries
        """
        # Ensure thread exists
        await self.ensure_thread_exists()
        
        # Get history
        history = await self.get_thread_messages()
        
        # Combine and sanitize
        all_messages = history + new_messages
        all_messages = sanitize_messages_for_openai(all_messages)
        
        # Save new user/system messages
        if save_to_thread:
            for msg in new_messages:
                if msg.role in ("user", "system"):
                    await self.save_message(msg)
        
        # Track messages to save
        messages_to_save: List[Message] = []
        final_content = ""
        
        # Run the agent
        async for event in self.run(
            messages=all_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            yield event
            
            # Track messages for saving
            if save_to_thread:
                if event.get("type") == "assistant_message":
                    msg_data = event.get("message", {})
                    if msg_data:
                        messages_to_save.append(Message(
                            role=msg_data.get("role", "assistant"),
                            content=msg_data.get("content"),
                            tool_calls=msg_data.get("tool_calls")
                        ))
                elif event.get("type") == "tool_result":
                    messages_to_save.append(Message(
                        role="tool",
                        content=event.get("content", ""),
                        tool_call_id=event.get("tool_call_id"),
                        name=event.get("tool_name")
                    ))
                elif event.get("type") == "agent_done":
                    final_content = event.get("final_content", "")
        
        # Save tracked messages
        if save_to_thread:
            await self.save_messages(messages_to_save)
            
            # Save final content if not already saved
            if final_content and not any(
                m.role == "assistant" and m.content == final_content
                for m in messages_to_save
            ):
                await self.save_message(Message(role="assistant", content=final_content))
    
    async def __aenter__(self) -> "KafkaAgent":
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.cleanup()
