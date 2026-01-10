"""
Kafka Agent Types
=================

Pydantic models for request/response schemas.
OpenAI-compatible formats for chat completions.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """OpenAI-compatible message format for requests."""
    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """
    OpenAI-compatible chat completion request.
    
    Note: The 'messages' field typically only needs to contain the NEW message(s),
    as the server will prepend the thread history automatically.
    """
    model: str = Field(..., description="Model ID to use")
    messages: List[ChatMessage] = Field(..., description="New message(s) to add")
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, gt=0)
    stream: Optional[bool] = Field(False)
    stop: Optional[List[str]] = None
    top_p: Optional[float] = Field(None, ge=0, le=1)
    frequency_penalty: Optional[float] = Field(None, ge=-2, le=2)
    presence_penalty: Optional[float] = Field(None, ge=-2, le=2)
    user: Optional[str] = None


class AgentRunRequest(BaseModel):
    """Request for running the agent."""
    messages: List[ChatMessage]
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class DeltaContent(BaseModel):
    """Delta object in streaming response."""
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class StreamChoice(BaseModel):
    """Choice object in streaming response."""
    index: int = 0
    delta: DeltaContent
    finish_reason: Optional[str] = None


class StreamChunkResponse(BaseModel):
    """OpenAI-compatible streaming chunk format."""
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[StreamChoice]


class MessageContent(BaseModel):
    """Message in non-streaming response."""
    role: str = "assistant"
    content: Optional[str] = None


class Choice(BaseModel):
    """Choice in non-streaming response."""
    index: int = 0
    message: MessageContent
    finish_reason: Optional[str] = None


class Usage(BaseModel):
    """Token usage in response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible non-streaming response format."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Optional[Usage] = None
