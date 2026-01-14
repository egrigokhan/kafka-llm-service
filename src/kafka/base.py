"""
Kafka Agent Base Class
======================

Abstract base class for Kafka agents.
Kafka is the name of our overall agent system.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncGenerator, Union

from src.llm import Message, CompletionResponse
from src.db import SupabaseClient, LocalDBClient
from src.tools import AgentToolProvider, ToolResultChunk
from src.agents import Agent

# Type alias for any DB client that supports our interface
DBClient = SupabaseClient | LocalDBClient

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
        self._db_client: Optional[DBClient] = None
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
        
        # Accumulate streaming content
        current_assistant_content = ""
        current_tool_calls: Dict[int, Dict[str, Any]] = {}
        accumulated_tool_results: Dict[str, str] = {}  # tool_call_id -> accumulated content
        
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
                # Handle tool result streaming - accumulate delta, save on complete
                if event.get("type") == "tool_result":
                    tool_call_id = event.get("tool_call_id", "")
                    delta = event.get("delta", "")
                    is_complete = event.get("is_complete", False)
                    
                    # Accumulate content
                    if tool_call_id not in accumulated_tool_results:
                        accumulated_tool_results[tool_call_id] = ""
                    accumulated_tool_results[tool_call_id] += delta
                    
                    # Save when complete
                    if is_complete:
                        messages_to_save.append(Message(
                            role="tool",
                            content=accumulated_tool_results[tool_call_id],
                            tool_call_id=tool_call_id,
                            name=event.get("tool_name")
                        ))
                
                # Handle OpenAI format chunks - accumulate content and tool_calls
                elif event.get("choices"):
                    choice = event["choices"][0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason")
                    
                    # Accumulate content
                    if delta.get("content"):
                        current_assistant_content += delta["content"]
                    
                    # Accumulate tool calls
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in current_tool_calls:
                                current_tool_calls[idx] = {
                                    "id": "", "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                }
                            if tc.get("id"):
                                current_tool_calls[idx]["id"] = tc["id"]
                            if tc.get("function", {}).get("name"):
                                current_tool_calls[idx]["function"]["name"] = tc["function"]["name"]
                            if tc.get("function", {}).get("arguments"):
                                current_tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]
                            # Preserve thought_signature for Gemini (required for multi-turn tool calling)
                            if tc.get("function", {}).get("thought_signature"):
                                current_tool_calls[idx]["function"]["thought_signature"] = tc["function"]["thought_signature"]
                    
                    # When LLM turn ends, save assistant message
                    if finish_reason == "tool_calls":
                        tool_calls_list = [current_tool_calls[i] for i in sorted(current_tool_calls.keys())]
                        messages_to_save.append(Message(
                            role="assistant",
                            content=current_assistant_content if current_assistant_content else None,
                            tool_calls=tool_calls_list
                        ))
                        # Reset for next iteration
                        current_assistant_content = ""
                        current_tool_calls = {}
                    elif finish_reason == "stop" and current_assistant_content:
                        messages_to_save.append(Message(
                            role="assistant",
                            content=current_assistant_content
                        ))
                        current_assistant_content = ""
                
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
