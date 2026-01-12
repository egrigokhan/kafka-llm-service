"""
Prompt Provider V1
==================

First version of the Kafka AI Agent prompt provider.
Loads all sections in the standard order with default environment values.
"""

from typing import Dict, List, Optional, Any, Union
from pathlib import Path

from .base import PromptProvider, PromptSection


class PromptProviderV1(PromptProvider):
    """
    Version 1 of the Kafka AI Agent prompt provider.
    
    Loads prompt sections from markdown files in a specific order.
    Supports template variable substitution for runtime customization.
    
    Default section order:
        1. intro - Overview and identity
        2. core_principles - The 6 guiding principles
        3. core_tools - Quick reference for all tools
        4. decision_tree - Tool selection flowchart
        5. workflow - Agent loop and communication rules
        6. environment - Language and sandbox settings
        7. operational - Verification, debugging, task management
        8. notebook_shell - Python notebook and shell guides
        9. search - SearchV2 web search
        10. webcrawler - WebCrawler content extraction
        11. agent - Agent/subagent reasoning
        12. domain_specific - Documents, People/Company Search, Meeting Bot
        13. appfactory - Third-party integrations
    
    Template Variables (use {{variable_name}} syntax):
        - working_language: Default working language (default: "English")
        - sandbox_os: Operating system (default: "Ubuntu 22.04")
        - sandbox_arch: Architecture (default: "linux/amd64")
        - sandbox_user: System user (default: "ubuntu")
        - sandbox_home: Home directory (default: "/home/user")
        - sandbox_working_dir: Working directory (default: "/workspace")
        - uploads_dir: Uploads subdirectory (default: "uploads/")
        - python_version: Python version (default: "3.10.12")
        - node_version: Node.js version (default: "20.18.0")
    
    Usage:
        # Basic usage with defaults
        provider = PromptProviderV1()
        prompt = provider.get_system_prompt()
        
        # With custom enrichment
        provider = PromptProviderV1()
        provider.enrich({
            "working_language": "Spanish",
            "sandbox_user": "admin"
        })
        prompt = provider.get_system_prompt()
        
        # Custom section selection
        provider = PromptProviderV1(sections=[
            "intro", "core_principles", "workflow"
        ])
        
        # Check for missing variables
        missing = provider.get_missing_variables()
        if missing:
            print(f"Warning: Missing variables: {missing}")
    """
    
    # Default values for template variables
    DEFAULT_ENRICHMENT: Dict[str, Any] = {
        "working_language": "English",
        "sandbox_os": "Ubuntu 22.04",
        "sandbox_arch": "linux/amd64",
        "sandbox_user": "ubuntu",
        "sandbox_home": "/home/user",
        "sandbox_working_dir": "/workspace",
        "uploads_dir": "uploads/",
        "python_version": "3.10.12",
        "node_version": "20.18.0",
    }
    
    # Section file mapping: section_name -> (filename, subfolder, order)
    SECTION_FILES: Dict[str, tuple] = {
        "intro": ("01_intro.md", None, 1),
        "core_principles": ("02_core_principles.md", None, 2),
        "core_tools": ("03_core_tools.md", None, 3),
        "decision_tree": ("04_decision_tree.md", None, 4),
        "workflow": ("05_workflow.md", None, 5),
        "environment": ("06_environment.md", None, 6),
        "operational": ("07_operational.md", None, 7),
        "notebook_shell": ("01_notebook_shell.md", "tools", 8),
        "search": ("02_search.md", "tools", 9),
        "webcrawler": ("03_webcrawler.md", "tools", 10),
        "agent": ("04_agent.md", "tools", 11),
        "domain_specific": ("05_domain_specific.md", "tools", 12),
        "appfactory": ("06_appfactory.md", "tools", 13),
    }
    
    # Default section order (all sections)
    DEFAULT_SECTION_ORDER: List[str] = [
        "intro",
        "core_principles",
        "core_tools",
        "decision_tree",
        "workflow",
        "environment",
        "operational",
        "notebook_shell",
        "search",
        "webcrawler",
        "agent",
        "domain_specific",
        "appfactory",
    ]
    
    def __init__(
        self,
        sections: Optional[List[str]] = None,
        base_path: Optional[Union[str, Path]] = None,
        auto_enrich_defaults: bool = True,
    ):
        """
        Initialize the V1 prompt provider.
        
        Args:
            sections: Optional list of section names to include (in order).
                     If None, all sections are included in default order.
                     Valid section names: intro, core_principles, core_tools,
                     decision_tree, workflow, environment, operational,
                     notebook_shell, search, webcrawler, agent,
                     domain_specific, appfactory
            base_path: Base path for loading section files. Defaults to
                      the 'sections' directory relative to this module.
            auto_enrich_defaults: If True, automatically enrich with default
                                 values on initialization. Default: True
        """
        super().__init__(sections=sections, base_path=base_path)
        
        # Apply default enrichment
        if auto_enrich_defaults:
            self.enrich(self.DEFAULT_ENRICHMENT.copy())
    
    def _load_sections(self) -> List[PromptSection]:
        """
        Load all prompt sections from markdown files.
        
        Returns:
            List of PromptSection objects
        """
        sections = []
        
        for section_name, (filename, subfolder, order) in self.SECTION_FILES.items():
            try:
                section = self._load_section_from_file(
                    filename=filename,
                    name=section_name,
                    order=order,
                    subfolder=subfolder,
                )
                sections.append(section)
            except FileNotFoundError as e:
                # Log warning but continue - section might be optional
                import warnings
                warnings.warn(f"Section file not found: {e}")
        
        return sections
    
    @classmethod
    def get_default_enrichment(cls) -> Dict[str, Any]:
        """
        Get a copy of the default enrichment values.
        
        Returns:
            Dictionary of default template variable values
        """
        return cls.DEFAULT_ENRICHMENT.copy()
    
    @classmethod
    def get_available_sections(cls) -> List[str]:
        """
        Get list of all available section names.
        
        Returns:
            List of section names
        """
        return list(cls.SECTION_FILES.keys())
    
    def create_minimal(self) -> "PromptProviderV1":
        """
        Create a minimal prompt with only essential sections.
        
        Returns:
            New PromptProviderV1 with minimal sections
        """
        minimal_sections = [
            "intro",
            "core_principles",
            "decision_tree",
            "workflow",
        ]
        return PromptProviderV1(sections=minimal_sections)
    
    def create_tools_only(self) -> "PromptProviderV1":
        """
        Create a prompt with only tool documentation.
        
        Returns:
            New PromptProviderV1 with tool sections only
        """
        tool_sections = [
            "core_tools",
            "notebook_shell",
            "search",
            "webcrawler",
            "agent",
            "domain_specific",
            "appfactory",
        ]
        return PromptProviderV1(sections=tool_sections)
    
    def without_tools(self) -> "PromptProviderV1":
        """
        Create a prompt without detailed tool documentation.
        
        Returns:
            New PromptProviderV1 without tool sections
        """
        non_tool_sections = [
            "intro",
            "core_principles",
            "core_tools",
            "decision_tree",
            "workflow",
            "environment",
            "operational",
        ]
        return PromptProviderV1(sections=non_tool_sections)


# Convenience factory functions
def create_default_provider(**enrichment) -> PromptProviderV1:
    """
    Create a default prompt provider with optional enrichment overrides.
    
    Args:
        **enrichment: Key-value pairs to override default enrichment
        
    Returns:
        Configured PromptProviderV1 instance
    """
    provider = PromptProviderV1()
    if enrichment:
        provider.enrich(enrichment)
    return provider


def create_minimal_provider(**enrichment) -> PromptProviderV1:
    """
    Create a minimal prompt provider with essential sections only.
    
    Args:
        **enrichment: Key-value pairs to override default enrichment
        
    Returns:
        Minimal PromptProviderV1 instance
    """
    provider = PromptProviderV1(sections=[
        "intro",
        "core_principles",
        "decision_tree",
        "workflow",
    ])
    if enrichment:
        provider.enrich(enrichment)
    return provider


def create_custom_provider(
    sections: List[str],
    **enrichment
) -> PromptProviderV1:
    """
    Create a custom prompt provider with specific sections.
    
    Args:
        sections: List of section names to include
        **enrichment: Key-value pairs for enrichment
        
    Returns:
        Custom PromptProviderV1 instance
    """
    provider = PromptProviderV1(sections=sections)
    if enrichment:
        provider.enrich(enrichment)
    return provider
