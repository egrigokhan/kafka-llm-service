"""
LLM Types
=========

This module contains all the type definitions for the LLM provider system.
These types are shared across all LLM providers.
"""

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
from enum import Enum


class Role(str, Enum):
    """
    Message roles following OpenAI's convention.
    
    - system: Instructions that define the assistant's behavior
    - user: Messages from the human user
    - assistant: Messages from the AI assistant
    - tool: Results from tool/function calls (for function calling)
    """
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """
    A single message in the conversation.
    
    This follows the OpenAI message format for maximum compatibility.
    All providers should convert to/from this format internally.
    
    Attributes:
        role: Who sent the message (system/user/assistant/tool)
        content: The text content of the message
        name: Optional name for the message sender (used in multi-user scenarios)
        tool_calls: Optional list of tool calls made by the assistant
        tool_call_id: ID of the tool call this message is responding to (for tool role)
    
    Example:
        >>> msg = Message(role="user", content="What is 2+2?")
        >>> msg.to_dict()
        {"role": "user", "content": "What is 2+2?"}
    """
    role: str = Field(..., description="The role of the message sender")
    content: Optional[str] = Field(None, description="The text content of the message")
    name: Optional[str] = Field(None, description="Optional name of the sender")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls made by assistant")
    tool_call_id: Optional[str] = Field(None, description="ID of tool call this responds to")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert message to dictionary, excluding None values.
        This is useful for API calls that don't accept null values.
        """
        d = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.name is not None:
            d["name"] = self.name
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d


class StreamChunk(BaseModel):
    """
    A single chunk from a streaming response.
    
    When streaming, the LLM returns content piece by piece. Each piece
    is wrapped in a StreamChunk with metadata about the stream state.
    
    Attributes:
        content: The new content in this chunk (may be empty string)
        role: The role (usually only in first chunk)
        tool_calls: Tool call deltas in this chunk
        finish_reason: Why the stream ended (null until final chunk)
                      - "stop": Natural completion
                      - "length": Max tokens reached
                      - "tool_calls": Model wants to call a tool
        model: The model that generated this chunk
        id: Unique identifier for this completion
    
    Example:
        >>> chunk = StreamChunk(content="Hello", finish_reason=None)
        >>> print(chunk.content)  # "Hello"
        >>> chunk.is_final  # False
    """
    content: Optional[str] = Field(default=None, description="The incremental content")
    role: Optional[str] = Field(default=None, description="Role (usually only in first chunk)")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="Tool call deltas")
    finish_reason: Optional[str] = Field(None, description="Reason stream ended")
    model: Optional[str] = Field(None, description="Model that generated response")
    id: Optional[str] = Field(None, description="Unique completion ID")
    
    # Keep delta as alias for backwards compatibility
    @property
    def delta(self) -> str:
        """Alias for content for backwards compatibility."""
        return self.content or ""
    
    @property
    def is_final(self) -> bool:
        """Check if this is the final chunk in the stream."""
        return self.finish_reason is not None


class CompletionResponse(BaseModel):
    """
    Complete (non-streaming) response from the LLM.
    
    This represents the full response when not using streaming.
    Contains the complete message plus usage statistics.
    
    Attributes:
        content: The full text response from the model
        role: Always "assistant" for completion responses
        finish_reason: Why generation stopped
        model: The model that generated the response
        id: Unique identifier for this completion
        usage: Token usage statistics (prompt_tokens, completion_tokens, total_tokens)
        tool_calls: Any tool calls the model wants to make
    
    Example:
        >>> response = await provider.completion(messages)
        >>> print(response.content)
        >>> print(f"Used {response.usage['total_tokens']} tokens")
    """
    content: Optional[str] = Field(None, description="The complete response text")
    role: str = Field(default="assistant", description="Always 'assistant'")
    finish_reason: Optional[str] = Field(None, description="Why generation stopped")
    model: Optional[str] = Field(None, description="Model that generated response")
    id: Optional[str] = Field(None, description="Unique completion ID")
    usage: Optional[Dict[str, int]] = Field(None, description="Token usage stats")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls to execute")
    
    def to_message(self) -> Message:
        """Convert this response to a Message for adding to conversation history."""
        return Message(
            role=self.role,
            content=self.content,
            tool_calls=self.tool_calls
        )


class LLMProviderError(Exception):
    """
    Base exception for LLM provider errors.
    
    Providers should raise this (or subclasses) for API errors,
    making it easier for callers to handle LLM-specific issues.
    
    Attributes:
        message: Human-readable error message
        status_code: HTTP status code if applicable
        provider: Name of the provider that raised the error
        original_error: The underlying exception if wrapping another error
    """
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        provider: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.provider = provider
        self.original_error = original_error
    
    def __str__(self) -> str:
        parts = [self.message]
        if self.provider:
            parts.insert(0, f"[{self.provider}]")
        if self.status_code:
            parts.append(f"(status: {self.status_code})")
        return " ".join(parts)
