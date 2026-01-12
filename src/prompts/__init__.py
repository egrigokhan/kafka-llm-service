"""
Kafka Prompt Provider System
============================

A modular, extensible system for managing AI agent prompts with:
- Template variable substitution ({{variable}} syntax)
- Section-based prompt composition
- Runtime enrichment with dynamic data
- Version-controlled prompt implementations

Usage:
    from prompts import PromptProviderV1
    
    provider = PromptProviderV1()
    provider.enrich({"working_language": "English", "sandbox_user": "ubuntu"})
    system_prompt = provider.get_system_prompt()
"""

from .base import PromptProvider, PromptSection
from .v1 import PromptProviderV1

__all__ = [
    "PromptProvider",
    "PromptSection", 
    "PromptProviderV1",
]
