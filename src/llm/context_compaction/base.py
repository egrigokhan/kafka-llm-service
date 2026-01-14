"""
Base classes and utilities for context compaction.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging


def is_context_length_error(error: Exception) -> bool:
    """
    Check if an error is a context length error from various providers.
    
    Handles:
    - Anthropic/Bedrock: "prompt is too long: X tokens > Y maximum"
    - Bedrock: "Input is too long for requested model"
    - Anthropic/Bedrock: "input length and `max_tokens` exceed context limit"
    - OpenAI: "context_length_exceeded" or similar
    - Google/Gemini: token limit errors
    - Generic token limit errors
    
    Args:
        error: The exception to check
        
    Returns:
        True if this is a context length error
    """
    error_str = str(error).lower()
    
    # Anthropic/Bedrock patterns
    if "prompt is too long" in error_str and "tokens" in error_str:
        return True
    if "input is too long" in error_str:
        return True
    # Combined input + max_tokens pattern (Anthropic/Bedrock)
    if "input length and" in error_str and "max_tokens" in error_str and "exceed context limit" in error_str:
        return True
    
    # OpenAI patterns
    if "context_length_exceeded" in error_str:
        return True
    if "maximum context length" in error_str:
        return True
    if "token limit" in error_str:
        return True
    
    # Google/Gemini patterns
    if "exceeds the maximum" in error_str and "token" in error_str:
        return True
    
    # Generic patterns
    if "too many tokens" in error_str:
        return True
    if "exceeds maximum" in error_str and "tokens" in error_str:
        return True
    
    # Check error body if available (for structured errors)
    if hasattr(error, 'body') and error.body:
        body_str = str(error.body).lower()
        if "prompt is too long" in body_str:
            return True
        if "input is too long" in body_str:
            return True
    
    return False


def find_safe_split_point(messages: List[Dict[str, Any]], target_split: int) -> int:
    """
    Find a safe split point that doesn't break tool use/result pairs.
    
    Rules:
    - Never split between an assistant message with tool_calls and its tool results
    - If the target split falls in the middle of a tool sequence, move back to before it
    
    Args:
        messages: List of messages to split
        target_split: The desired split point (e.g., 75% mark)
        
    Returns:
        Safe split index that respects message boundaries
    """
    if target_split <= 0:
        return 0
    if target_split >= len(messages):
        return len(messages)
    
    # Start from target and work backwards to find a safe point
    safe_split = target_split
    
    # Check if we're in the middle of a tool sequence
    while safe_split > 0:
        current_msg = messages[safe_split - 1] if safe_split > 0 else None
        next_msg = messages[safe_split] if safe_split < len(messages) else None
        
        # If current message is assistant with tool_calls, we need to include all tool results
        if (current_msg and current_msg.get("role") == "assistant" and 
            current_msg.get("tool_calls")):
            # Move split point to before this assistant message
            safe_split -= 1
            continue
            
        # If next message is a tool result, we need to find its tool_use
        if next_msg and next_msg.get("role") == "tool":
            # Move split point back to include the tool_use message
            safe_split -= 1
            continue
            
        # We found a safe split point
        break
    
    return safe_split


def validate_message_structure(
    messages: List[Dict[str, Any]], 
    logger: Optional[logging.Logger] = None
) -> List[Dict[str, Any]]:
    """
    Validate and fix message structure to ensure API compatibility.
    
    Fixes:
    - Removes orphaned tool results without corresponding tool uses
    - Ensures no empty assistant messages
    - Validates tool_call_id references
    
    Args:
        messages: List of messages to validate
        logger: Optional logger
        
    Returns:
        Validated message list
    """
    if not messages:
        return messages
    
    # Track tool_call_ids from assistant messages
    valid_tool_call_ids = set()
    
    # First pass: collect all tool_call_ids
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tool_call in msg["tool_calls"]:
                if tool_call.get("id"):
                    valid_tool_call_ids.add(tool_call["id"])
    
    # Second pass: filter messages
    validated = []
    for msg in messages:
        # Skip orphaned tool results
        if msg.get("role") == "tool":
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id not in valid_tool_call_ids:
                if logger:
                    logger.warning(f"Removing orphaned tool result with id: {tool_call_id}")
                continue
        
        # Skip empty assistant messages (no content and no tool_calls)
        if (msg.get("role") == "assistant" and 
            not msg.get("content") and 
            not msg.get("tool_calls")):
            if logger:
                logger.warning("Removing empty assistant message")
            continue
            
        validated.append(msg)
    
    return validated


class ContextCompactionProvider(ABC):
    """
    Abstract base class for context compaction strategies.
    
    Context compaction is triggered when the conversation history exceeds
    the model's context window. Implementations can use different strategies
    such as summarization, truncation, or hybrid approaches.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the context compaction provider.
        
        Args:
            logger: Optional logger for debugging
        """
        self.logger = logger or logging.getLogger(__name__)
    
    @abstractmethod
    async def compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        model: str,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Compact the conversation history to fit within context limits.
        
        Args:
            messages: Full conversation history
            system_prompt: Original system prompt to preserve
            model: Model being used (for context window info)
            **kwargs: Additional provider-specific options
            
        Returns:
            Compacted message list
        """
        pass
    
    def should_compact(self, error: Exception) -> bool:
        """
        Check if the given error indicates that compaction is needed.
        
        Args:
            error: The exception from the LLM API
            
        Returns:
            True if compaction should be attempted
        """
        return is_context_length_error(error)
