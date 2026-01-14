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
from openai import AsyncOpenAI
from portkey_ai import createHeaders, PORTKEY_GATEWAY_URL

from typing import TYPE_CHECKING

from .base import (
    LLMProvider,
    Message,
    StreamChunk,
    CompletionResponse,
    LLMProviderError,
)
from .utils import (
    get_provider_from_model,
    normalize_messages_for_provider,
    prune_images_in_messages,
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
        virtual_keys: Optional[Dict[str, Optional[str]]] = None,
        config: Optional[str] = None,
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
            virtual_key: Single Portkey virtual key (deprecated, use virtual_keys).
            virtual_keys: Dict of provider-specific virtual keys:
                         {"openai": "vk-xxx", "anthropic": "vk-yyy", "google": "vk-zzz"}
                         The correct key is selected based on the model being used.
            config: Portkey config ID for multi-provider routing (alternative to virtual_keys).
            model: Model identifier (e.g., "gpt-4o", "claude-sonnet-4").
            default_temperature: Default sampling temperature (0.0-2.0).
            default_max_tokens: Default max tokens. None = provider default.
            tool_provider: Optional tool provider for function calling.
            **portkey_kwargs: Additional Portkey client configuration.
        
        Raises:
            ValueError: If api_key is not provided and not found in environment.
            ValueError: If no virtual keys are available.
        """
        super().__init__(tool_provider=tool_provider)
        
        # Get credentials from params or environment
        self.api_key = api_key or os.environ.get("PORTKEY_API_KEY")
        self.config = config or os.environ.get("PORTKEY_CONFIG")
        
        # Provider-specific virtual keys (preferred for multi-provider support)
        self._virtual_keys: Dict[str, Optional[str]] = virtual_keys or {}
        
        # Fallback: single virtual_key (used for all providers - not recommended)
        if virtual_key:
            self._virtual_keys["openai"] = virtual_key
        elif os.environ.get("PORTKEY_VIRTUAL_KEY"):
            self._virtual_keys["openai"] = os.environ.get("PORTKEY_VIRTUAL_KEY")
        
        # For backwards compatibility
        self.virtual_key = self._virtual_keys.get("openai")
        
        # Debug logging
        print(f"🔧 PortkeyLLMProvider init:")
        print(f"   api_key: {self.api_key[:10] if self.api_key else None}...")
        print(f"   config: {self.config}")
        print(f"   virtual_keys:")
        for provider, vk in self._virtual_keys.items():
            print(f"      {provider}: {vk[:15] if vk else None}...")
        print(f"   model: {model}")
        
        if not self.api_key:
            raise ValueError(
                "Portkey API key required. Pass api_key or set PORTKEY_API_KEY env var."
            )
        
        # Need at least one virtual key or a config
        has_any_virtual_key = any(v for v in self._virtual_keys.values() if v)
        if not has_any_virtual_key and not self.config:
            raise ValueError(
                "At least one virtual_key or config is required. "
                "Set virtual_keys={'openai': 'vk-xxx', 'anthropic': 'vk-yyy'} for multi-provider support."
            )
        
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        
        # Store provider mapping for per-request routing
        self._provider_map = {
            "openai": "openai",
            "anthropic": "anthropic",
            "google": "google"
        }
        
        # We'll create AsyncOpenAI clients per-request with provider-specific virtual keys
    
    def _get_virtual_key_for_provider(self, provider: str) -> Optional[str]:
        """Get the virtual key for a specific provider."""
        # Try provider-specific key first
        if provider in self._virtual_keys and self._virtual_keys[provider]:
            return self._virtual_keys[provider]
        
        # For google, also check "gemini" key
        if provider == "google" and self._virtual_keys.get("gemini"):
            return self._virtual_keys["gemini"]
        
        # Fallback to openai key (single virtual_key mode)
        if self._virtual_keys.get("openai"):
            print(f"⚠️ No {provider} virtual key found, falling back to OpenAI key")
            return self._virtual_keys["openai"]
        
        return None
    
    def _create_client_for_provider(self, provider: str = "openai") -> AsyncOpenAI:
        """
        Create an AsyncOpenAI client configured for a specific provider.
        
        This is useful for auxiliary tasks like context compaction that need
        to make separate LLM calls.
        
        Args:
            provider: The LLM provider to use ("openai", "anthropic", "google")
            
        Returns:
            AsyncOpenAI client configured with Portkey headers
        """
        portkey_provider = self._provider_map.get(provider, "openai")
        virtual_key = self._get_virtual_key_for_provider(provider)
        
        if not virtual_key:
            raise ValueError(f"No virtual key available for provider: {provider}")
        
        header_kwargs: Dict[str, Any] = {
            "provider": portkey_provider,
            "api_key": self.api_key,
            "virtual_key": virtual_key,
        }
        
        if self.config:
            header_kwargs["config"] = self.config
        
        portkey_headers = createHeaders(**header_kwargs)
        
        return AsyncOpenAI(
            base_url=PORTKEY_GATEWAY_URL,
            api_key="xxx",  # Dummy key - auth is via Portkey headers
            default_headers=portkey_headers
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
        # Use model from kwargs if provided, otherwise use self.model
        model_to_use = kwargs.pop("model", self.model)
        
        # Log model being used for debugging
        if model_to_use != self.model:
            print(f"🔄 Using model from request: {model_to_use} (default was: {self.model})")
        else:
            print(f"📝 Using default model: {model_to_use}")
        
        # Prune images to keep only newest 19 for provider compatibility
        message_dicts = prune_images_in_messages(message_dicts, max_images=19)
        
        # Normalize messages for provider (e.g., Google/Gemini via Portkey)
        provider = get_provider_from_model(model_to_use)
        message_dicts = normalize_messages_for_provider(message_dicts, provider)
        
        # For Gemini models, use non-streaming to properly capture thought_signature
        # (required for multi-turn tool calling with Gemini)
        use_streaming = True
        if provider == "google":
            use_streaming = False
            print(f"📝 Using non-streaming mode for Gemini to capture thought_signature")
        
        params: Dict[str, Any] = {
            "model": model_to_use,
            "messages": message_dicts,
            "stream": use_streaming,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        
        # Model-specific parameter handling
        # GPT-5 uses max_completion_tokens instead of max_tokens
        if model_to_use.startswith("gpt-5"):
            if max_tokens is not None:
                params["max_completion_tokens"] = max_tokens
            elif self.default_max_tokens is not None:
                params["max_completion_tokens"] = self.default_max_tokens
        else:
            # Standard max_tokens for other models
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
            elif self.default_max_tokens is not None:
                params["max_tokens"] = self.default_max_tokens
            elif provider == "anthropic":
                # Anthropic REQUIRES max_tokens - use a sensible default
                params["max_tokens"] = 8192
            
        if stop:
            params["stop"] = stop
        
        # Add tools if available
        tools = await self.get_tools()
        if tools:
            params["tools"] = tools
        
        # Gemini-specific parameters (if using Gemini model)
        if provider == "google" and "gemini" in model_to_use.lower():
            # Add Gemini-specific generation config via extra_body
            # This helps Portkey route correctly to Gemini
            if "extra_body" not in kwargs:
                kwargs["extra_body"] = {}
            if "generationConfig" not in kwargs["extra_body"]:
                kwargs["extra_body"]["generationConfig"] = {}
            # Set reasonable defaults for Gemini
            if "temperature" not in kwargs["extra_body"]["generationConfig"]:
                kwargs["extra_body"]["generationConfig"]["temperature"] = temperature if temperature is not None else self.default_temperature
        
        # Add provider information to help Portkey route correctly
        # This is critical for models like Claude/Gemini that need to route to the right provider
        portkey_provider = self._provider_map.get(provider, "openai")
        
        # Get the virtual key for this specific provider
        provider_virtual_key = self._get_virtual_key_for_provider(provider)
        
        # Create headers with provider information for Portkey routing
        try:
            header_kwargs: Dict[str, Any] = {
                "provider": portkey_provider,
                "api_key": self.api_key,
                # strict_open_ai_compliance=False is CRITICAL for Gemini thought_signature
                # Without this, Portkey won't pass through provider-specific fields like thought_signature
                "strict_open_ai_compliance": False,
            }
            # Use config if available, otherwise use provider-specific virtual_key
            if self.config:
                header_kwargs["config"] = self.config
                print(f"🔀 Using config with {portkey_provider} provider for model {model_to_use}")
            elif provider_virtual_key:
                header_kwargs["virtual_key"] = provider_virtual_key
                print(f"🔀 Using {portkey_provider} virtual_key for model {model_to_use}")
            else:
                raise ValueError(f"No virtual key available for provider: {portkey_provider}")
            
            portkey_headers = createHeaders(**header_kwargs)
        except Exception as e:
            print(f"⚠️ Warning: Could not create Portkey headers: {e}")
            print(f"   Provider: {portkey_provider}, Model: {model_to_use}")
            raise
        
        # Create AsyncOpenAI client with Portkey gateway URL and provider headers
        # This matches the reference implementation pattern
        client = AsyncOpenAI(
            base_url=PORTKEY_GATEWAY_URL,
            api_key="xxx",  # Not needed when using virtual_key
            default_headers=portkey_headers
        )
        
        # Add any extra kwargs (top_p, penalties, etc.)
        # Note: model was already extracted above, so it won't be in kwargs anymore
        params.update(kwargs)
        
        try:
            # Make request via Portkey gateway
            response = await client.chat.completions.create(**params)
            
            # Handle non-streaming response (for Gemini to capture thought_signature)
            if not use_streaming:
                completion_id = response.id
                model_used = response.model or model_to_use
                
                if response.choices and len(response.choices) > 0:
                    choice = response.choices[0]
                    message = choice.message
                    
                    # Build tool_calls list with thought_signature if present
                    tool_calls_list = None
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        tool_calls_list = []
                        for idx, tc in enumerate(message.tool_calls):
                            tc_dict: Dict[str, Any] = {"index": idx}
                            tc_dict["id"] = tc.id
                            tc_dict["type"] = tc.type or "function"
                            tc_dict["function"] = {
                                "name": tc.function.name if tc.function else "",
                                "arguments": tc.function.arguments if tc.function else "{}"
                            }
                            # Preserve thought_signature for Gemini (required for multi-turn tool calling)
                            if tc.function and hasattr(tc.function, 'thought_signature') and tc.function.thought_signature:
                                tc_dict["function"]["thought_signature"] = tc.function.thought_signature
                                print(f"📝 Captured thought_signature for tool {tc.function.name}")
                            tool_calls_list.append(tc_dict)
                    
                    # Yield single "chunk" with full response (simulating streaming)
                    yield StreamChunk(
                        content=message.content,
                        role=message.role,
                        tool_calls=tool_calls_list,
                        finish_reason=choice.finish_reason,
                        model=model_used,
                        id=completion_id
                    )
                return
            
            # Handle streaming response
            stream = response
            completion_id = None
            model_used = model_to_use
            
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
                                    # Preserve thought_signature for Gemini (required for multi-turn tool calling)
                                    if hasattr(tc.function, 'thought_signature') and tc.function.thought_signature:
                                        tc_dict["function"]["thought_signature"] = tc.function.thought_signature
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
        
        # Use model from kwargs if provided, otherwise use self.model
        model_to_use = kwargs.pop("model", self.model)
        
        # Prune images to keep only newest 19 for provider compatibility
        message_dicts = prune_images_in_messages(message_dicts, max_images=19)
        
        # Normalize messages for provider (e.g., Google/Gemini via Portkey)
        provider = get_provider_from_model(model_to_use)
        message_dicts = normalize_messages_for_provider(message_dicts, provider)
        
        # Build request parameters (same as streaming, but stream=False)
        params: Dict[str, Any] = {
            "model": model_to_use,
            "messages": message_dicts,
            "stream": False,
            "temperature": temperature if temperature is not None else self.default_temperature,
        }
        
        # Model-specific parameter handling
        # GPT-5 uses max_completion_tokens instead of max_tokens
        if model_to_use.startswith("gpt-5"):
            if max_tokens is not None:
                params["max_completion_tokens"] = max_tokens
            elif self.default_max_tokens is not None:
                params["max_completion_tokens"] = self.default_max_tokens
        else:
            # Standard max_tokens for other models
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
            elif self.default_max_tokens is not None:
                params["max_tokens"] = self.default_max_tokens
            elif provider == "anthropic":
                # Anthropic REQUIRES max_tokens - use a sensible default
                params["max_tokens"] = 8192
            
        if stop:
            params["stop"] = stop
        
        # Add tools if available
        tools = await self.get_tools()
        if tools:
            params["tools"] = tools
        
        # Gemini-specific parameters (if using Gemini model)
        if provider == "google" and "gemini" in model_to_use.lower():
            # Add Gemini-specific generation config via extra_body
            if "extra_body" not in kwargs:
                kwargs["extra_body"] = {}
            if "generationConfig" not in kwargs["extra_body"]:
                kwargs["extra_body"]["generationConfig"] = {}
            if "temperature" not in kwargs["extra_body"]["generationConfig"]:
                kwargs["extra_body"]["generationConfig"]["temperature"] = temperature if temperature is not None else self.default_temperature
        
        # Add provider information to help Portkey route correctly
        portkey_provider = self._provider_map.get(provider, "openai")
        
        # Get the virtual key for this specific provider
        provider_virtual_key = self._get_virtual_key_for_provider(provider)
        
        # Create headers with provider information for Portkey routing
        try:
            header_kwargs: Dict[str, Any] = {
                "provider": portkey_provider,
                "api_key": self.api_key,
                # strict_open_ai_compliance=False is CRITICAL for Gemini thought_signature
                "strict_open_ai_compliance": False,
            }
            if self.config:
                header_kwargs["config"] = self.config
                print(f"🔀 Using config with {portkey_provider} provider for model {model_to_use}")
            elif provider_virtual_key:
                header_kwargs["virtual_key"] = provider_virtual_key
                print(f"🔀 Using {portkey_provider} virtual_key for model {model_to_use}")
            else:
                raise ValueError(f"No virtual key available for provider: {portkey_provider}")
            
            portkey_headers = createHeaders(**header_kwargs)
        except Exception as e:
            print(f"⚠️ Warning: Could not create Portkey headers: {e}")
            print(f"   Provider: {portkey_provider}, Model: {model_to_use}")
            raise
        
        # Create AsyncOpenAI client with Portkey gateway URL and provider headers
        client = AsyncOpenAI(
            base_url=PORTKEY_GATEWAY_URL,
            api_key="xxx",  # Not needed when using config/virtual_key
            default_headers=portkey_headers
        )
        
        # Add any extra kwargs (model was already extracted above)
        params.update(kwargs)
        
        try:
            # Make non-streaming request via Portkey gateway
            response = await client.chat.completions.create(**params)
            
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
                        tool_calls = []
                        for tc in choice.message.tool_calls:
                            tc_dict = {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            }
                            # Preserve thought_signature for Gemini (required for multi-turn tool calling)
                            if hasattr(tc.function, 'thought_signature') and tc.function.thought_signature:
                                tc_dict["function"]["thought_signature"] = tc.function.thought_signature
                            tool_calls.append(tc_dict)
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
                model=response.model or model_to_use,
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
        
        Note: We create clients per-request, so there's no persistent client to close.
        """
        # No persistent client to clean up - clients are created per-request
        pass
