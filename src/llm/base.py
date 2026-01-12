"""
LLM Provider Base Class
=======================

This module defines the abstract base class for all LLM providers in the system.
Any LLM backend (OpenAI, Anthropic, Portkey, etc.) should inherit from LLMProvider
and implement the required abstract methods.

The design follows these principles:
1. Provider-agnostic message format (OpenAI-compatible)
2. Streaming-first approach with optional non-streaming
3. Clear separation between configuration and execution
4. Type-safe with Pydantic models

Usage Example:
-------------
```python
from src.llm import PortkeyLLMProvider, Message

provider = PortkeyLLMProvider(
    api_key="your-portkey-api-key",
    virtual_key="your-virtual-key",
    model="gpt-4o"
)

messages = [
    Message(role="system", content="You are a helpful assistant."),
    Message(role="user", content="Hello!")
]

# Streaming response
async for chunk in provider.stream_completion(messages):
    print(chunk.delta, end="", flush=True)

# Non-streaming response
response = await provider.completion(messages)
print(response.content)
```
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, List, Any, Dict, TYPE_CHECKING

from src.llm.types import (
    Role,
    Message,
    StreamChunk,
    CompletionResponse,
    LLMProviderError,
)

if TYPE_CHECKING:
    from src.tools import ToolProvider


# Re-export types for backward compatibility
__all__ = [
    "Role",
    "Message",
    "StreamChunk",
    "CompletionResponse",
    "LLMProvider",
    "LLMProviderError",
]


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    This class defines the interface that all LLM providers must implement.
    It's designed to be provider-agnostic while maintaining OpenAI API compatibility.
    
    Subclasses MUST implement:
        - stream_completion(): Streaming response generation
        - completion(): Non-streaming response generation
    
    Subclasses MAY override:
        - validate_messages(): Custom message validation
        - get_model_info(): Return model capabilities
    
    Design Decisions:
    ----------------
    1. Async-first: All methods are async to support high-concurrency servers
    2. Streaming default: stream_completion is the primary method; completion 
       can be implemented using stream_completion if needed
    3. Message format: Uses OpenAI's message format as the standard
    4. Error handling: Providers should raise LLMProviderError for LLM-specific errors
    5. Tool support: Optional ToolProvider for function calling capabilities
    
    Configuration:
    -------------
    Providers receive configuration through __init__. Common parameters:
        - model: The model identifier (e.g., "gpt-4o", "claude-3-opus")
        - temperature: Sampling temperature (0.0 to 2.0)
        - max_tokens: Maximum tokens to generate
        - tool_provider: Optional ToolProvider for function calling
        - Additional provider-specific parameters
    
    Example Implementation:
    ---------------------
    ```python
    class MyProvider(LLMProvider):
        def __init__(self, api_key: str, model: str = "my-model", tool_provider=None):
            super().__init__(tool_provider=tool_provider)
            self.api_key = api_key
            self.model = model
        
        async def stream_completion(
            self, 
            messages: List[Message],
            **kwargs
        ) -> AsyncGenerator[StreamChunk, None]:
            # Implementation here
            async for chunk in my_api.stream(messages):
                yield StreamChunk(delta=chunk.text)
        
        async def completion(
            self,
            messages: List[Message],
            **kwargs
        ) -> CompletionResponse:
            # Implementation here
            response = await my_api.complete(messages)
            return CompletionResponse(content=response.text)
    ```
    """
    
    def __init__(self, tool_provider: Optional["ToolProvider"] = None):
        """
        Initialize the LLM provider.
        
        Args:
            tool_provider: Optional tool provider for function calling.
                          If provided, tools will be available for completions.
        """
        self._tool_provider = tool_provider
    
    @property
    def tool_provider(self) -> Optional["ToolProvider"]:
        """Get the tool provider if configured."""
        return self._tool_provider
    
    @tool_provider.setter
    def tool_provider(self, provider: Optional["ToolProvider"]) -> None:
        """Set or update the tool provider."""
        self._tool_provider = provider
    
    def has_tools(self) -> bool:
        """Check if a tool provider is configured."""
        return self._tool_provider is not None
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        """
        Get available tools from the tool provider.
        
        Returns:
            List of tool definitions in OpenAI function format.
            Returns empty list if no tool provider is configured.
        """
        if self._tool_provider is None:
            return []
        return await self._tool_provider.get_tools()
    
    @abstractmethod
    async def stream_completion(
        self,
        messages: List[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Generate a streaming completion for the given messages.
        
        This is the primary method for generating responses. It yields
        StreamChunk objects as the model generates content, allowing
        for real-time display of responses.
        
        Args:
            messages: List of conversation messages. Must contain at least
                     one message. Messages are processed in order.
            temperature: Sampling temperature (0.0 = deterministic, 2.0 = creative).
                        If None, uses provider's default.
            max_tokens: Maximum tokens to generate. If None, uses provider's default
                       or model's maximum context minus prompt tokens.
            stop: List of sequences where generation should stop.
                 The model will stop when any of these sequences is generated.
            **kwargs: Provider-specific parameters. Common ones include:
                     - top_p: Nucleus sampling parameter
                     - frequency_penalty: Penalize repeated tokens
                     - presence_penalty: Penalize tokens that appeared before
                     - user: End-user ID for abuse monitoring
        
        Yields:
            StreamChunk: Incremental response chunks. The final chunk will have
                        finish_reason set (typically "stop" or "length").
        
        Raises:
            LLMProviderError: If the API call fails
            ValueError: If messages are invalid
        
        Example:
            >>> async for chunk in provider.stream_completion(messages):
            ...     print(chunk.delta, end="", flush=True)
            ...     if chunk.is_final:
            ...         print(f"\\n[Finished: {chunk.finish_reason}]")
        
        Implementation Notes:
            - MUST yield at least one chunk (even if empty with finish_reason)
            - SHOULD handle rate limits with appropriate retries
            - SHOULD convert provider-specific errors to LLMProviderError
            - MUST be safe to cancel/interrupt mid-stream
        """
        # This is an abstract method - subclasses must implement
        # The yield statement is here to make this a generator
        yield StreamChunk()  # pragma: no cover
    
    @abstractmethod
    async def completion(
        self,
        messages: List[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> CompletionResponse:
        """
        Generate a non-streaming completion for the given messages.
        
        Use this when you need the complete response before processing,
        or when streaming is not necessary (e.g., background tasks).
        
        Args:
            messages: List of conversation messages (same as stream_completion)
            temperature: Sampling temperature (same as stream_completion)
            max_tokens: Maximum tokens to generate (same as stream_completion)
            stop: Stop sequences (same as stream_completion)
            **kwargs: Provider-specific parameters (same as stream_completion)
        
        Returns:
            CompletionResponse: The complete response with content and metadata.
                              Includes usage statistics when available.
        
        Raises:
            LLMProviderError: If the API call fails
            ValueError: If messages are invalid
        
        Example:
            >>> response = await provider.completion(messages)
            >>> print(response.content)
            >>> print(f"Tokens used: {response.usage['total_tokens']}")
        
        Implementation Notes:
            - Can be implemented by collecting stream_completion chunks
            - SHOULD return usage statistics when available
            - SHOULD handle rate limits with appropriate retries
        """
        ...  # pragma: no cover
    
    def validate_messages(self, messages: List[Message]) -> List[Message]:
        """
        Validate and potentially transform messages before sending.
        
        Override this in subclasses to add provider-specific validation
        or message transformation. The default implementation just checks
        that messages is not empty.
        
        Args:
            messages: List of messages to validate
        
        Returns:
            List[Message]: Validated (and possibly transformed) messages
        
        Raises:
            ValueError: If messages are invalid
        
        Example override:
            >>> def validate_messages(self, messages):
            ...     messages = super().validate_messages(messages)
            ...     # Ensure system message is first
            ...     if messages[0].role != "system":
            ...         messages.insert(0, Message(role="system", content="..."))
            ...     return messages
        """
        if not messages:
            raise ValueError("Messages list cannot be empty")
        return messages
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Return information about the current model configuration.
        
        Override this to provide model-specific capabilities and limits.
        Useful for clients that need to know context limits, supported
        features, etc.
        
        Returns:
            Dict with model information. Common keys:
                - model: Model identifier
                - max_context_tokens: Maximum context window
                - supports_vision: Whether model supports images
                - supports_tools: Whether model supports function calling
        
        Example:
            >>> info = provider.get_model_info()
            >>> print(f"Max tokens: {info.get('max_context_tokens', 'unknown')}")
        """
        return {}
