"""
Kafka Agent Module
==================

Kafka is the name of our overall agent system.
This module provides the core agent functionality.
"""

from .base import KafkaAgent
from .v1 import KafkaV1Provider
from .types import (
    ChatMessage,
    ChatCompletionRequest,
    AgentRunRequest,
    DeltaContent,
    StreamChoice,
    StreamChunkResponse,
    MessageContent,
    Choice,
    Usage,
    ChatCompletionResponse,
)
from .utils import (
    convert_to_internal_message,
    sanitize_messages_for_openai,
    messages_to_dict_list,
)

__all__ = [
    # Base
    "KafkaAgent",
    # Providers
    "KafkaV1Provider",
    # Types
    "ChatMessage",
    "ChatCompletionRequest",
    "AgentRunRequest",
    "DeltaContent",
    "StreamChoice",
    "StreamChunkResponse",
    "MessageContent",
    "Choice",
    "Usage",
    "ChatCompletionResponse",
    # Utils
    "convert_to_internal_message",
    "sanitize_messages_for_openai",
    "messages_to_dict_list",
]
