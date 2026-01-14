"""
V1 Context Compaction: Summarization-based approach.

This implementation summarizes older conversation history while
preserving recent messages exactly as-is.
"""

import json
from typing import List, Dict, Any, Optional
import logging

from .base import (
    ContextCompactionProvider,
    find_safe_split_point,
    validate_message_structure,
)


# Model-specific max output tokens
MODEL_MAX_OUTPUT_TOKENS: Dict[str, int] = {
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-5": 32768,
    "gpt-5.2": 32768,
    "claude-sonnet-4-5": 16384,
    "claude-3-5-sonnet": 8192,
    "claude-3-opus": 4096,
    "gemini-2.0-flash": 8192,
    "gemini-2.5-pro": 65536,
    "gemini-2.5-flash": 65536,
}


def get_max_output_tokens(model: str) -> int:
    """Get max output tokens for a model, with sensible defaults."""
    # Check for exact match
    if model in MODEL_MAX_OUTPUT_TOKENS:
        return MODEL_MAX_OUTPUT_TOKENS[model]
    
    # Check for prefix matches
    for key, value in MODEL_MAX_OUTPUT_TOKENS.items():
        if model.startswith(key):
            return value
    
    # Default
    return 8192


class SummarizationCompactionProvider(ContextCompactionProvider):
    """
    Context compaction using LLM-based summarization.
    
    Strategy:
    1. Preserve the original system prompt
    2. Summarize ~75% of the conversation history
    3. Preserve the last ~25% of messages exactly as-is
    4. Add the summary as a new system message
    """
    
    def __init__(
        self,
        llm_client: Any,
        summarize_ratio: float = 0.75,
        min_messages_to_summarize: int = 10,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the summarization compaction provider.
        
        Args:
            llm_client: OpenAI-compatible async client for making summarization calls
            summarize_ratio: Fraction of messages to summarize (default 0.75)
            min_messages_to_summarize: Minimum messages before summarization kicks in
            logger: Optional logger
        """
        super().__init__(logger)
        self.llm_client = llm_client
        self.summarize_ratio = summarize_ratio
        self.min_messages_to_summarize = min_messages_to_summarize
    
    async def compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        model: str,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Compact conversation by summarizing older messages.
        
        Args:
            messages: Full conversation history
            system_prompt: Original system prompt to preserve
            model: Model to use for summarization
            **kwargs: Additional options (reduce_max_tokens, etc.)
            
        Returns:
            Compacted message list with summary
        """
        self.logger.info(f"Starting summarization compaction. Total messages: {len(messages)}")
        
        # Separate system messages from conversation
        system_messages = []
        non_system_messages = []
        
        for msg in messages:
            if msg.get("role") == "system" and not non_system_messages:
                # Still collecting initial system messages
                system_messages.append(msg)
            else:
                non_system_messages.append(msg)
        
        # Check if we have enough messages to summarize
        if len(non_system_messages) < self.min_messages_to_summarize:
            self.logger.info(
                f"Not enough messages to summarize ({len(non_system_messages)} < {self.min_messages_to_summarize})"
            )
            return messages
        
        # Calculate split point
        target_split = int(len(non_system_messages) * self.summarize_ratio)
        split_point = find_safe_split_point(non_system_messages, target_split)
        messages_to_summarize = non_system_messages[:split_point]
        messages_to_keep = non_system_messages[split_point:]
        
        self.logger.info(
            f"Target split: {target_split}, Safe split: {split_point}. "
            f"Summarizing {len(messages_to_summarize)} messages, keeping {len(messages_to_keep)}"
        )
        
        # Build summarization prompt
        summary_prompt = """You are an AI assistant tasked with creating a concise summary of a conversation history.

Your goal is to preserve:
1. All key information, decisions made, and actions taken
2. Important context and background information
3. Tool execution results and their outcomes
4. Any errors or issues encountered
5. The current state of any ongoing tasks

Focus on:
- What was accomplished
- What is currently in progress
- Important data or results that were discovered
- Any user preferences or requirements stated

Create a clear, structured summary that allows the conversation to continue seamlessly.
The summary should be in markdown format with clear sections."""

        # Prepare messages for summarization
        summarization_messages = [
            {"role": "system", "content": summary_prompt},
            {
                "role": "user", 
                "content": f"Please summarize the following conversation history:\n\n{json.dumps(messages_to_summarize, indent=2)}"
            }
        ]
        
        try:
            # Build call parameters
            call_params = {
                "model": model,
                "messages": summarization_messages,
                "temperature": 0.3,  # Lower temperature for focused summaries
            }
            
            # Use appropriate max tokens (keep summaries concise)
            summarization_max_tokens = min(8192, get_max_output_tokens(model) // 4)
            
            # GPT-5 uses max_completion_tokens
            if model.startswith("gpt-5"):
                call_params["max_completion_tokens"] = summarization_max_tokens
            else:
                call_params["max_tokens"] = summarization_max_tokens
            
            # Make the summarization call
            self.logger.info(f"Making summarization call with model: {model}")
            summary_response = await self.llm_client.chat.completions.create(**call_params)
            
            summary_content = summary_response.choices[0].message.content
            
            # Create the summary system message with a marker
            summary_message = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": f"[CONVERSATION HANDOFF - {len(messages_to_summarize)} messages summarized]\n\n{summary_content}",
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            }
            
            # Reconstruct the message list
            new_messages = []
            
            # 1. Keep original system messages
            new_messages.extend(system_messages)
            
            # 2. Add the summary as a new system message
            new_messages.append(summary_message)
            
            # 3. Add the preserved recent messages
            new_messages.extend(messages_to_keep)
            
            # Validate the final message structure
            new_messages = validate_message_structure(new_messages, self.logger)
            
            self.logger.info(
                f"Summarization complete. New message count: {len(new_messages)} "
                f"(was {len(messages)})"
            )
            
            # Debug: Show message structure
            self.logger.debug("Message structure after summarization:")
            for i, msg in enumerate(new_messages[-5:]):
                role = msg.get("role", "unknown")
                has_content = bool(msg.get("content"))
                has_tool_calls = bool(msg.get("tool_calls"))
                is_tool = msg.get("role") == "tool"
                tool_call_id = msg.get("tool_call_id", "N/A") if is_tool else "N/A"
                self.logger.debug(
                    f"  [{i}] {role}: content={has_content}, "
                    f"tool_calls={has_tool_calls}, tool_call_id={tool_call_id}"
                )
            
            return new_messages
            
        except Exception as e:
            self.logger.error(f"Failed to summarize conversation: {e}")
            self.logger.info("Falling back to simple truncation")
            
            # Fallback: Safe truncation that respects boundaries
            safe_cutoff = find_safe_split_point(
                non_system_messages, 
                max(50, len(non_system_messages) - 50)
            )
            fallback_messages = system_messages + non_system_messages[safe_cutoff:]
            return validate_message_structure(fallback_messages, self.logger)


class TruncationCompactionProvider(ContextCompactionProvider):
    """
    Simple truncation-based context compaction.
    
    This is a fallback strategy that simply removes older messages
    while respecting tool call boundaries.
    """
    
    def __init__(
        self,
        keep_count: int = 50,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the truncation compaction provider.
        
        Args:
            keep_count: Number of recent messages to keep
            logger: Optional logger
        """
        super().__init__(logger)
        self.keep_count = keep_count
    
    async def compact(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        model: str,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Compact conversation by truncating older messages.
        
        Args:
            messages: Full conversation history
            system_prompt: Original system prompt to preserve
            model: Model (not used in truncation)
            **kwargs: Additional options
            
        Returns:
            Truncated message list
        """
        self.logger.info(f"Starting truncation compaction. Total messages: {len(messages)}")
        
        # Separate system messages
        system_messages = []
        non_system_messages = []
        
        for msg in messages:
            if msg.get("role") == "system" and not non_system_messages:
                system_messages.append(msg)
            else:
                non_system_messages.append(msg)
        
        # Find safe truncation point
        if len(non_system_messages) <= self.keep_count:
            self.logger.info("Not enough messages to truncate")
            return messages
        
        target = len(non_system_messages) - self.keep_count
        safe_cutoff = find_safe_split_point(non_system_messages, target)
        
        # Rebuild message list
        new_messages = system_messages + non_system_messages[safe_cutoff:]
        new_messages = validate_message_structure(new_messages, self.logger)
        
        self.logger.info(
            f"Truncation complete. New message count: {len(new_messages)} "
            f"(was {len(messages)})"
        )
        
        return new_messages
