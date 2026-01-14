"""
LLM Provider Utilities
======================

Utility functions for provider-specific message handling and normalization.
"""

from typing import List, Dict, Any


def get_provider_from_model(model: str) -> str:
    """
    Infer the provider from the model name.
    
    Args:
        model: Model identifier (e.g., "gpt-4o", "claude-sonnet-4", "gemini-2.0")
        
    Returns:
        Provider name: "openai", "anthropic", "google", or "unknown"
    """
    model_lower = model.lower()
    if "gpt" in model_lower or "o1" in model_lower:
        return "openai"
    elif "claude" in model_lower or "sonnet" in model_lower or "opus" in model_lower or "haiku" in model_lower:
        return "anthropic"
    elif "gemini" in model_lower:
        return "google"
    else:
        return "unknown"


def normalize_messages_for_provider(messages: List[Dict[str, Any]], provider: str) -> List[Dict[str, Any]]:
    """
    Normalize messages for provider-specific requirements.
    
    Different providers have different message format requirements:
    - OpenAI: Standard format (content can be string or list)
    - Anthropic: Standard format (content can be string or list)
    - Google/Gemini: Prefers list format for multimodal content
    
    Args:
        messages: List of message dicts
        provider: Provider name ("openai", "anthropic", "google")
        
    Returns:
        Normalized message list
    """
    normalized = []
    for msg in messages:
        content = msg.get("content")
        
        # Handle content format based on provider
        if provider == "google":
            # Gemini prefers list format for multimodal content
            if isinstance(content, str):
                # Convert string content to list format
                normalized_msg = {**msg, "content": [{"type": "text", "text": content}]}
            elif isinstance(content, list):
                # Already in list format, ensure items have proper structure
                normalized_content = []
                for item in content:
                    if isinstance(item, str):
                        # Convert string items to text dict
                        normalized_content.append({"type": "text", "text": item})
                    elif isinstance(item, dict):
                        # Already in dict format, keep as-is
                        normalized_content.append(item)
                    else:
                        # Unknown format, wrap as text
                        normalized_content.append({"type": "text", "text": str(item)})
                normalized_msg = {**msg, "content": normalized_content}
            else:
                # None or other - keep as-is (will be handled by Portkey)
                normalized_msg = msg
        else:
            # OpenAI and Anthropic accept both string and list formats
            # Portkey will handle the conversion, so we can pass through
            normalized_msg = msg
        
        normalized.append(normalized_msg)
    
    return normalized


def prune_images_in_messages(messages: List[Dict[str, Any]], max_images: int = 19) -> List[Dict[str, Any]]:
    """
    Prune images to keep only the newest N images across the conversation.
    
    Some providers have limits on the number of images that can be included.
    This function keeps only the most recent images.
    
    Args:
        messages: List of message dicts
        max_images: Maximum number of images to keep
        
    Returns:
        Messages with pruned images
    """
    all_images = []
    
    # Collect all images with their message index
    for idx, msg in enumerate(messages):
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in ("image", "image_url"):
                    all_images.append((idx, item))
    
    # If we have more than max_images, remove oldest ones
    if len(all_images) > max_images:
        # Keep only the last max_images
        images_to_keep = all_images[-max_images:]
        images_to_remove = set(all_images[:-max_images])
        
        # Remove old images from messages
        pruned_messages = []
        for idx, msg in enumerate(messages):
            content = msg.get("content")
            if isinstance(content, list):
                pruned_content = [
                    item for item in content
                    if not (isinstance(item, dict) and item.get("type") in ("image", "image_url") and (idx, item) in images_to_remove)
                ]
                pruned_msg = {**msg, "content": pruned_content}
                pruned_messages.append(pruned_msg)
            else:
                pruned_messages.append(msg)
        return pruned_messages
    
    return messages
