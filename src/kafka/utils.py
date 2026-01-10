"""
Kafka Agent Utilities
=====================

Helper functions for message handling and conversion.
"""

from typing import List

from src.llm import Message
from .types import ChatMessage


def convert_to_internal_message(chat_msg: ChatMessage) -> Message:
    """Convert OpenAI-format ChatMessage to internal Message format."""
    return Message(
        role=chat_msg.role,
        content=chat_msg.content,
        name=chat_msg.name,
        tool_calls=chat_msg.tool_calls,
        tool_call_id=chat_msg.tool_call_id
    )


def sanitize_messages_for_openai(messages: List[Message]) -> List[Message]:
    """
    Sanitize messages to ensure OpenAI API compatibility.
    
    OpenAI requires that:
    1. Every 'tool' message must follow an 'assistant' message with tool_calls
    2. Each tool message's tool_call_id must match a tool_call in the preceding assistant message
    
    This function filters out orphan tool messages that would cause API errors.
    """
    if not messages:
        return messages
    
    sanitized = []
    valid_tool_call_ids = set()
    
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            # Track the tool_call_ids from this assistant message
            valid_tool_call_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
            sanitized.append(msg)
        elif msg.role == "tool":
            # Only include tool messages that have a matching tool_call_id
            if msg.tool_call_id and msg.tool_call_id in valid_tool_call_ids:
                sanitized.append(msg)
                # Remove from valid set since it's been "used"
                valid_tool_call_ids.discard(msg.tool_call_id)
            else:
                # Skip orphan tool message
                print(f"⚠️ Skipping orphan tool message (tool_call_id: {msg.tool_call_id}, name: {msg.name})")
        else:
            # For user, system, or assistant without tool_calls - reset valid_tool_call_ids
            if msg.role != "assistant" or not msg.tool_calls:
                valid_tool_call_ids = set()
            sanitized.append(msg)
    
    return sanitized


def messages_to_dict_list(messages: List[Message]) -> List[dict]:
    """Convert a list of Messages to a list of dicts."""
    return [m.to_dict() for m in messages]
