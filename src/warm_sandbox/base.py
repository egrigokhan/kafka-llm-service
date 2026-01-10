"""
Base class for warm sandbox factories.
"""

from abc import ABC, abstractmethod
from typing import Optional


class WarmSandboxFactory(ABC):
    """
    Abstract base class for warm sandbox factories.
    
    Claims pre-warmed sandboxes from a pool service.
    """
    
    @abstractmethod
    async def get_warm_sandbox(self, environment_id: str) -> Optional[str]:
        """
        Get a warm sandbox for the given environment ID.
        
        Args:
            environment_id: The environment/image ID to get a sandbox for
            
        Returns:
            The sandbox ID if available, None if not
        """
        pass
