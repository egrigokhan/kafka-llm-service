"""
Base Prompt Provider
====================

Abstract base class for prompt providers with template enrichment support.
"""

import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from pathlib import Path


@dataclass
class PromptSection:
    """
    Represents a single section of a prompt.
    
    Attributes:
        name: Unique identifier for the section
        content: The raw content (may contain {{variables}})
        order: Sort order for section placement
        enabled: Whether this section is included
        metadata: Additional metadata for the section
    """
    name: str
    content: str
    order: int = 0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate section after initialization."""
        if not self.name:
            raise ValueError("Section name cannot be empty")
        if self.content is None:
            self.content = ""


class PromptProvider(ABC):
    """
    Abstract base class for prompt providers.
    
    Provides:
    - Template variable substitution with {{key}} syntax
    - Section-based prompt composition
    - Runtime enrichment with dynamic data
    - Section ordering and filtering
    
    Subclasses must implement:
    - _load_sections(): Load and return list of PromptSection objects
    """
    
    # Regex pattern for template variables: {{variable_name}}
    TEMPLATE_PATTERN = re.compile(r'\{\{(\w+)\}\}')
    
    def __init__(
        self,
        sections: Optional[List[str]] = None,
        base_path: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize the prompt provider.
        
        Args:
            sections: Optional list of section names to include (in order).
                     If None, all sections are included in their default order.
            base_path: Base path for loading section files. Defaults to
                      the 'sections' directory relative to this module.
        """
        self._sections: Dict[str, PromptSection] = {}
        self._section_order: List[str] = []
        self._enrichment_data: Dict[str, Any] = {}
        self._custom_section_order: Optional[List[str]] = sections
        
        # Set base path for section files
        if base_path is None:
            self._base_path = Path(__file__).parent / "sections"
        else:
            self._base_path = Path(base_path)
        
        # Load sections from subclass implementation
        self._initialize_sections()
    
    def _initialize_sections(self) -> None:
        """Initialize sections from the subclass implementation."""
        loaded_sections = self._load_sections()
        
        for section in loaded_sections:
            self._sections[section.name] = section
        
        # Set section order
        if self._custom_section_order:
            # Use custom order, filtering out non-existent sections
            self._section_order = [
                name for name in self._custom_section_order 
                if name in self._sections
            ]
        else:
            # Use default order based on section.order attribute
            sorted_sections = sorted(
                self._sections.values(),
                key=lambda s: (s.order, s.name)
            )
            self._section_order = [s.name for s in sorted_sections]
    
    @abstractmethod
    def _load_sections(self) -> List[PromptSection]:
        """
        Load and return all available prompt sections.
        
        Subclasses must implement this to define their sections.
        Can load from files, define inline, or mix both approaches.
        
        Returns:
            List of PromptSection objects
        """
        pass
    
    def _load_section_from_file(
        self,
        filename: str,
        name: Optional[str] = None,
        order: int = 0,
        subfolder: Optional[str] = None,
    ) -> PromptSection:
        """
        Load a section from a markdown file.
        
        Args:
            filename: Name of the file to load
            name: Section name (defaults to filename without extension)
            order: Sort order for the section
            subfolder: Optional subfolder within sections directory
            
        Returns:
            PromptSection loaded from file
            
        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        if subfolder:
            file_path = self._base_path / subfolder / filename
        else:
            file_path = self._base_path / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"Section file not found: {file_path}")
        
        content = file_path.read_text(encoding="utf-8")
        
        # Default name from filename (strip number prefix and extension)
        if name is None:
            # Handle formats like "01_intro.md" -> "intro"
            base_name = filename.rsplit(".", 1)[0]
            if "_" in base_name:
                name = base_name.split("_", 1)[1]
            else:
                name = base_name
        
        return PromptSection(
            name=name,
            content=content,
            order=order,
            metadata={"source_file": str(file_path)}
        )
    
    def _load_sections_from_directory(
        self,
        subfolder: Optional[str] = None,
        pattern: str = "*.md",
    ) -> List[PromptSection]:
        """
        Load all sections from a directory.
        
        Files are expected to be named with order prefix: "01_name.md"
        
        Args:
            subfolder: Subfolder within sections directory
            pattern: Glob pattern for files to load
            
        Returns:
            List of PromptSection objects sorted by filename
        """
        if subfolder:
            dir_path = self._base_path / subfolder
        else:
            dir_path = self._base_path
        
        if not dir_path.exists():
            return []
        
        sections = []
        for file_path in sorted(dir_path.glob(pattern)):
            if file_path.is_file():
                # Extract order from filename prefix (e.g., "01_" -> 1)
                filename = file_path.name
                order = 0
                if "_" in filename:
                    prefix = filename.split("_", 1)[0]
                    try:
                        order = int(prefix)
                    except ValueError:
                        pass
                
                section = self._load_section_from_file(
                    filename=filename,
                    order=order,
                    subfolder=subfolder,
                )
                sections.append(section)
        
        return sections
    
    def enrich(self, data: Dict[str, Any]) -> "PromptProvider":
        """
        Enrich the prompt with runtime data for template substitution.
        
        Template variables use {{key}} syntax. When get_system_prompt() is called,
        these placeholders are replaced with the provided values.
        
        Args:
            data: Dictionary of key-value pairs for template substitution.
                  Keys should match template variable names (without braces).
                  
        Returns:
            self (for method chaining)
            
        Example:
            provider.enrich({
                "working_language": "English",
                "user_name": "John",
                "current_date": "2025-01-12"
            })
        """
        self._enrichment_data.update(data)
        return self
    
    def clear_enrichment(self) -> "PromptProvider":
        """
        Clear all enrichment data.
        
        Returns:
            self (for method chaining)
        """
        self._enrichment_data.clear()
        return self
    
    def _substitute_variables(self, content: str) -> str:
        """
        Substitute template variables in content.
        
        Variables not found in enrichment data are left as-is.
        
        Args:
            content: Content with {{variable}} placeholders
            
        Returns:
            Content with variables substituted
        """
        def replace_match(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name in self._enrichment_data:
                value = self._enrichment_data[var_name]
                # Convert non-strings to string representation
                if not isinstance(value, str):
                    value = str(value)
                return value
            # Leave unmatched variables as-is (or could raise/warn)
            return match.group(0)
        
        return self.TEMPLATE_PATTERN.sub(replace_match, content)
    
    def get_section(self, name: str) -> Optional[PromptSection]:
        """
        Get a specific section by name.
        
        Args:
            name: Section name
            
        Returns:
            PromptSection if found, None otherwise
        """
        return self._sections.get(name)
    
    def get_section_content(self, name: str, enrich: bool = True) -> Optional[str]:
        """
        Get the content of a specific section.
        
        Args:
            name: Section name
            enrich: Whether to apply template substitution
            
        Returns:
            Section content (optionally enriched), or None if not found
        """
        section = self._sections.get(name)
        if section is None:
            return None
        
        content = section.content
        if enrich:
            content = self._substitute_variables(content)
        return content
    
    def list_sections(self) -> List[str]:
        """
        List all available section names in order.
        
        Returns:
            List of section names
        """
        return list(self._section_order)
    
    def list_all_sections(self) -> List[str]:
        """
        List all loaded section names (regardless of order/enabled status).
        
        Returns:
            List of all section names
        """
        return list(self._sections.keys())
    
    def enable_section(self, name: str) -> "PromptProvider":
        """
        Enable a section for inclusion in the prompt.
        
        Args:
            name: Section name
            
        Returns:
            self (for method chaining)
        """
        if name in self._sections:
            self._sections[name].enabled = True
        return self
    
    def disable_section(self, name: str) -> "PromptProvider":
        """
        Disable a section from inclusion in the prompt.
        
        Args:
            name: Section name
            
        Returns:
            self (for method chaining)
        """
        if name in self._sections:
            self._sections[name].enabled = False
        return self
    
    def set_section_order(self, order: List[str]) -> "PromptProvider":
        """
        Set custom section ordering.
        
        Args:
            order: List of section names in desired order.
                  Sections not in this list will be excluded.
                  
        Returns:
            self (for method chaining)
        """
        self._section_order = [
            name for name in order 
            if name in self._sections
        ]
        return self
    
    def add_section(
        self,
        name: str,
        content: str,
        order: Optional[int] = None,
        position: Optional[int] = None,
    ) -> "PromptProvider":
        """
        Add a new section or replace an existing one.
        
        Args:
            name: Section name
            content: Section content
            order: Sort order (used if position not specified)
            position: Explicit position in section order list
            
        Returns:
            self (for method chaining)
        """
        if order is None:
            # Default to end of current sections
            max_order = max((s.order for s in self._sections.values()), default=0)
            order = max_order + 1
        
        self._sections[name] = PromptSection(
            name=name,
            content=content,
            order=order,
        )
        
        # Update order list
        if name not in self._section_order:
            if position is not None:
                self._section_order.insert(position, name)
            else:
                self._section_order.append(name)
        
        return self
    
    def remove_section(self, name: str) -> "PromptProvider":
        """
        Remove a section entirely.
        
        Args:
            name: Section name
            
        Returns:
            self (for method chaining)
        """
        if name in self._sections:
            del self._sections[name]
        if name in self._section_order:
            self._section_order.remove(name)
        return self
    
    def get_template_variables(self) -> List[str]:
        """
        Get all template variables used across all sections.
        
        Returns:
            List of unique variable names (without braces)
        """
        variables = set()
        for section in self._sections.values():
            matches = self.TEMPLATE_PATTERN.findall(section.content)
            variables.update(matches)
        return sorted(variables)
    
    def get_missing_variables(self) -> List[str]:
        """
        Get template variables that haven't been enriched.
        
        Returns:
            List of variable names without enrichment data
        """
        all_vars = set(self.get_template_variables())
        enriched_vars = set(self._enrichment_data.keys())
        return sorted(all_vars - enriched_vars)
    
    def get_system_prompt(
        self,
        include_disabled: bool = False,
        separator: str = "\n\n",
    ) -> str:
        """
        Generate the complete system prompt.
        
        Combines all enabled sections in order, with template variables
        substituted from enrichment data.
        
        Args:
            include_disabled: Whether to include disabled sections
            separator: String to join sections with
            
        Returns:
            Complete system prompt string
        """
        parts = []
        
        for name in self._section_order:
            section = self._sections.get(name)
            if section is None:
                continue
            
            if not section.enabled and not include_disabled:
                continue
            
            content = self._substitute_variables(section.content)
            if content.strip():
                parts.append(content)
        
        return separator.join(parts)
    
    def validate(self) -> Dict[str, Any]:
        """
        Validate the prompt provider configuration.
        
        Returns:
            Dictionary with validation results:
            - valid: bool
            - missing_variables: list of unset template variables
            - empty_sections: list of sections with no content
            - warnings: list of warning messages
        """
        result = {
            "valid": True,
            "missing_variables": [],
            "empty_sections": [],
            "warnings": [],
        }
        
        # Check for missing variables
        missing = self.get_missing_variables()
        if missing:
            result["missing_variables"] = missing
            result["warnings"].append(
                f"Template variables without values: {', '.join(missing)}"
            )
        
        # Check for empty sections
        for name, section in self._sections.items():
            if not section.content.strip():
                result["empty_sections"].append(name)
                result["warnings"].append(f"Section '{name}' is empty")
        
        # Check section order references valid sections
        for name in self._section_order:
            if name not in self._sections:
                result["warnings"].append(
                    f"Section order references non-existent section: {name}"
                )
                result["valid"] = False
        
        return result
    
    def __repr__(self) -> str:
        enabled_count = sum(1 for s in self._sections.values() if s.enabled)
        return (
            f"{self.__class__.__name__}("
            f"sections={len(self._sections)}, "
            f"enabled={enabled_count}, "
            f"enriched_vars={len(self._enrichment_data)})"
        )
    
    def __str__(self) -> str:
        """Return the system prompt when converted to string."""
        return self.get_system_prompt()
