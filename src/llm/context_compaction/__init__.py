"""
Context Compaction Module

Provides context window management through intelligent summarization
when conversation history exceeds model limits.
"""

from .base import (
    ContextCompactionProvider,
    is_context_length_error,
    find_safe_split_point,
    validate_message_structure,
)
from .v1 import SummarizationCompactionProvider, TruncationCompactionProvider

__all__ = [
    "ContextCompactionProvider",
    "SummarizationCompactionProvider",
    "TruncationCompactionProvider",
    "is_context_length_error",
    "find_safe_split_point",
    "validate_message_structure",
]
