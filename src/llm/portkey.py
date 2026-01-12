"""
Portkey LLM Provider
====================

Implementation of LLMProvider using Portkey AI Gateway.

Portkey provides a unified API to access multiple LLM providers (OpenAI, Anthropic,
Cohere, Azure, etc.) with features like:
- Automatic retries and fallbacks
- Request caching
- Cost tracking
- Rate limit handling

Configuration:
-------------
You need a Portkey API key and a "virtual key" that maps to your actual
LLM provider credentials. Set up virtual keys in the Portkey dashboard.

Environment Variables:
    PORTKEY_API_KEY: Your Portkey API key
    PORTKEY_VIRTUAL_KEY: Virtual key for the LLM provider

Example:
-------
```python
provider = PortkeyLLMProvider(
    api_key="pk-xxx",
    virtual_key="openai-xxx",
    model="gpt-4o"
)

messages = [Message(role="user", content="Hello!")]
async for chunk in provider.stream_completion(messages):
    print(chunk.delta, end="")
```
"""

import os
from typing import AsyncGenerator, Optional, List, Any, Dict
from portkey_ai import Portkey, AsyncPortkey

from typing import TYPE_CHECKING

from .base import (
    LLMProvider,
    Message,
    StreamChunk,
    CompletionResponse,
    LLMProviderError,
)

if TYPE_CHECKING:
    from src.tools import ToolProvider


class PortkeyLLMProvider(LLMProvider):
    """
    LLM Provider implementation using Portkey AI Gateway.
    
    Portkey acts as a proxy/gateway that routes requests to various LLM providers.
    This gives us flexibility to switch between providers without code changes.
    
    Attributes:
        client: Async Portkey client for API calls
        model: The model to use for completions
        default_temperature: Default temperature for completions
        default_max_tokens: Default max tokens for completions
    
    Example:
        >>> provider = PortkeyLLMProvider(
        ...     api_key=os.environ["PORTKEY_API_KEY"],
        ...     virtual_key=os.environ["PORTKEY_VIRTUAL_KEY"],
        ...     model="gpt-4o"
        ... )
        >>> 
        >>> messages = [Message(role="user", content="Hi!")]
        >>> async for chunk in provider.stream_completion(messages):
        ...     print(chunk.delta, end="", flush=True)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        virtual_key: Optional[str] = None,
        model: str = "gpt-4o",
        default_temperature: float = 0.7,
        default_max_tokens: Optional[int] = None,
        tool_provider: Optional["ToolProvider"] = None,
        **portkey_kwargs: Any
    ):
        """
        Initialize the Portkey LLM Provider.
        
        Args:
            api_key: Portkey API key. Falls back to PORTKEY_API_KEY env var.
            virtual_key: Portkey virtual key for the LLM provider.
                        Falls back to PORTKEY_VIRTUAL_KEY env var.
            model: Model identifier (e.g., "gpt-4o", "claude-3-opus-20240229").
                  Must be valid for the provider behind the virtual key.
            default_temperature: Default sampling temperature (0.0-2.0).
            default_max_tokens: Default max tokens. None = provider default.
            tool_provider: Optional tool provider for function calling.
            **portkey_kwargs: Additional Portkey client configuration:
                - base_url: Custom Portkey base URL
                - timeout: Request timeout in seconds
                - config: Portkey config ID for advanced routing
                - trace_id: Custom trace ID for logging
        
        Raises:
            ValueError: If api_key or virtual_key are not provided and
                       not found in environment variables.
        """
        super().__init__(tool_provider=tool_provider)
        
        # Get credentials from params or environment
        self.api_key = api_key or os.environ.get("PORTKEY_API_KEY")
        self.virtual_key = virtual_key or os.environ.get("PORTKEY_VIRTUAL_KEY")
        
        if not self.api_key:
            raise ValueError(
                "Portkey API key required. Pass api_key or set PORTKEY_API_KEY env var."
            )
        if not self.virtual_key:
            raise ValueError(
                "Virtual key required. Pass virtual_key or set PORTKEY_VIRTUAL_KEY env var."
            )
        
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        
        # Initialize async Portkey client
        # The virtual_key tells Portkey which provider credentials to use
        self.client = AsyncPortkey(
            api_key=self.api_key,
            virtual_key=self.virtual_key,
            **portkey_kwargs
        )
    
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
        Generate a streaming completion using Portkey.
        
        Connects to Portkey's chat completions API with streaming enabled.
        Chunks are yielded as they arrive from the model.
        
        Args:
            messages: Conversation messages (validated before sending)
            temperature: Sampling temperature (uses default if None)
            max_tokens: Max tokens to generate (uses default if None)
            stop: Stop sequences
            **kwargs: Additional parameters passed to the API:
                - top_p: Nucleus sampling threshold
                - frequency_penalty: Token frequency penalty
                - presence_penalty: Token presence penalty
                - user: End-user identifier
        
        Yields:
            StreamChunk objects containing:
                - delta: New content in this chunk
                - finish_reason: Set on final chunk
                - model: Model that generated response
                - id: Completion ID
        
        Raises:
            LLMProviderError: On API errors (auth, rate limit, etc.)
        """
        # Validate and convert messages
        validated = self.validate_messages(messages)
        message_dicts = [m.to_dict() for m in validated]
        
        # Build request parameters
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": message_dicts,
            "stream": True,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        
        # Add optional parameters
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        elif self.default_max_tokens is not None:
            params["max_tokens"] = self.default_max_tokens
            
        if stop:
            params["stop"] = stop
        
        # Add tools if available
        tools = await self.get_tools()
        if tools:
            params["tools"] = tools
        
        # Add any extra kwargs (top_p, penalties, etc.)
        params.update(kwargs)
        
        try:
            # Make streaming request to Portkey
            stream = await self.client.chat.completions.create(**params)
            
            completion_id = None
            model_used = self.model
            
            # Iterate over streaming response
            async for chunk in stream:
                # Extract chunk data
                # Portkey follows OpenAI's streaming format
                if chunk.id:
                    completion_id = chunk.id
                if chunk.model:
                    model_used = chunk.model
                
                # Get the delta content (may be None or empty)
                delta_content = None
                delta_role = None
                delta_tool_calls = None
                finish_reason = None
                
                if chunk.choices and len(chunk.choices) > 0:
                    choice = chunk.choices[0]
                    if choice.delta:
                        if choice.delta.content:
                            delta_content = choice.delta.content
                        if choice.delta.role:
                            delta_role = choice.delta.role
                        # Handle tool calls
                        if hasattr(choice.delta, 'tool_calls') and choice.delta.tool_calls:
                            delta_tool_calls = []
                            for tc in choice.delta.tool_calls:
                                tc_dict: Dict[str, Any] = {"index": tc.index}
                                if tc.id:
                                    tc_dict["id"] = tc.id
                                if tc.type:
                                    tc_dict["type"] = tc.type
                                if tc.function:
                                    tc_dict["function"] = {}
                                    if tc.function.name:
                                        tc_dict["function"]["name"] = tc.function.name
                                    if tc.function.arguments:
                                        tc_dict["function"]["arguments"] = tc.function.arguments
                                delta_tool_calls.append(tc_dict)
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                
                yield StreamChunk(
                    content=delta_content,
                    role=delta_role,
                    tool_calls=delta_tool_calls,
                    finish_reason=finish_reason,
                    model=model_used,
                    id=completion_id
                )
                
        except Exception as e:
            # Wrap any errors in our custom exception type
            raise LLMProviderError(
                message=str(e),
                provider="Portkey",
                original_error=e
            ) from e
    
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
        Generate a non-streaming completion using Portkey.
        
        Makes a single request and waits for the complete response.
        Use this when you need the full response before processing.
        
        Args:
            messages: Conversation messages
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            stop: Stop sequences
            **kwargs: Additional API parameters
        
        Returns:
            CompletionResponse with:
                - content: Full response text
                - finish_reason: Why generation stopped
                - model: Model used
                - id: Completion ID
                - usage: Token usage statistics
        
        Raises:
            LLMProviderError: On API errors
        """
        # Validate and convert messages
        validated = self.validate_messages(messages)
        message_dicts = [m.to_dict() for m in validated]
        
        # Build request parameters (same as streaming, but stream=False)
        params: Dict[str, Any] = {
            "model": self.model,
            "messages": message_dicts,
            "stream": False,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        elif self.default_max_tokens is not None:
            params["max_tokens"] = self.default_max_tokens
            
        if stop:
            params["stop"] = stop
        
        # Add tools if available
        tools = await self.get_tools()
        if tools:
            params["tools"] = tools
        
        params.update(kwargs)
        
        try:
            # Make non-streaming request
            response = await self.client.chat.completions.create(**params)
            
            # Extract response data
            content = None
            finish_reason = None
            tool_calls = None
            
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                if choice.message:
                    content = choice.message.content
                    # Handle tool calls if present
                    if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                        tool_calls = [
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            for tc in choice.message.tool_calls
                        ]
                finish_reason = choice.finish_reason
            
            # Build usage dict if available
            usage = None
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            
            return CompletionResponse(
                content=content,
                role="assistant",
                finish_reason=finish_reason,
                model=response.model or self.model,
                id=response.id,
                usage=usage,
                tool_calls=tool_calls
            )
            
        except Exception as e:
            raise LLMProviderError(
                message=str(e),
                provider="Portkey",
                original_error=e
            ) from e
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Return information about the current Portkey configuration.
        
        Returns:
            Dict containing:
                - model: Current model identifier
                - provider: "Portkey"
                - default_temperature: Default temperature setting
                - default_max_tokens: Default max tokens (if set)
        """
        info = {
            "model": self.model,
            "provider": "Portkey",
            "default_temperature": self.default_temperature,
        }
        if self.default_max_tokens:
            info["default_max_tokens"] = self.default_max_tokens
        return info
    
    async def close(self) -> None:
        """
        Close the Portkey client connection.
        
        Call this when done with the provider to clean up resources.
        Safe to call multiple times.
        """
        if hasattr(self.client, 'close'):
            await self.client.close()
