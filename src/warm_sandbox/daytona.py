"""
Daytona warm sandbox factory implementation.
"""

import os
import logging
from typing import Optional

import httpx

from .base import WarmSandboxFactory

logger = logging.getLogger(__name__)


def _get_warm_service_url() -> str:
    """Get the warm sandbox service URL from environment."""
    return os.getenv("WARM_SANDBOX_SERVICE_URL", "http://localhost:8001")


class DaytonaWarmSandboxFactory(WarmSandboxFactory):
    """
    Daytona implementation of the warm sandbox factory.
    """
    
    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url or _get_warm_service_url()
        self._client = httpx.AsyncClient(timeout=10.0)
    
    async def get_warm_sandbox(self, environment_id: str) -> Optional[str]:
        """
        Get a warm sandbox for the given environment ID.
        
        Args:
            environment_id: The environment/image ID to get a sandbox for
            
        Returns:
            The sandbox ID if available, None if not
        """
        url = f"{self._base_url}/claim/{environment_id}"

        try:
            response = await self._client.post(url)

            if response.status_code == 200:
                data = response.json()
                sandbox_id = data["sandbox_id"]
                return sandbox_id

            elif response.status_code == 404:
                return None

            else:
                return None

        except httpx.ConnectError:
            logger.warning(f"[WARM] Could not connect to warm sandbox service at {self._base_url}")
            return None
        except httpx.TimeoutException:
            logger.warning(f"[WARM] Timeout connecting to warm sandbox service")
            return None
        except Exception as e:
            logger.error(f"[WARM] Error claiming warm sandbox: {e}")
            return None
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
