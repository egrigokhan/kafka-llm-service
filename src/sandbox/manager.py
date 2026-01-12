"""
Sandbox Manager
===============

Manages sandbox lifecycle for threads, handling:
- Creating new sandboxes for new threads
- Connecting to existing running sandboxes
- Restarting stopped/expired sandboxes
- Claiming sandboxes with thread-specific data

Supports non-blocking operation:
- get_sandbox_if_ready() - returns immediately with sandbox or None
- ensure_sandbox_background() - kicks off creation in background
"""

import os
import asyncio
from typing import Any, Dict, Optional, Set, Protocol, TYPE_CHECKING

from .base import Sandbox
from .daytona import DaytonaSandbox

if TYPE_CHECKING:
    from src.db import SupabaseClient, LocalDBClient
    from src.warm_sandbox import WarmSandboxFactory


class DBClientProtocol(Protocol):
    """Protocol for DB clients that support sandbox operations."""
    async def get_thread_sandbox_id(self, thread_id: str) -> Optional[str]: ...
    async def update_thread_sandbox_id(self, thread_id: str, sandbox_id: str) -> Dict[str, Any]: ...
    async def get_thread_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]: ...
    async def get_thread_config(self, thread_id: str) -> Optional[Dict[str, Any]]: ...


class SandboxManager:
    """
    Manages sandbox lifecycle for threads.
    
    Handles three cases:
    1. New thread (no sandbox_id) → create new sandbox, save ID to DB
    2. Existing thread with running sandbox → return as-is
    3. Existing thread with stopped sandbox → restart and reclaim
    
    Usage:
        manager = SandboxManager(
            db_client=db,
            environment_id="my-env",
            warm_factory=warm_factory  # optional
        )
        
        sandbox = await manager.ensure_sandbox(
            thread_id="thread-123",
            claim_data={"THREAD_ID": "thread-123", ...}
        )
    """
    
    # Default Daytona environment for thread sandboxes
    DEFAULT_ENV_ID = "kafka-lite-vm-0.0.10"
    
    def __init__(
        self,
        db_client: "DBClientProtocol",
        environment_id: Optional[str] = None,
        warm_factory: Optional["WarmSandboxFactory"] = None
    ):
        """
        Initialize the sandbox manager.
        
        Args:
            db_client: Database client for thread operations (Supabase or LocalDBClient)
            environment_id: Environment/template ID for sandboxes (default: kafka-lite-vm-0.0.10)
            warm_factory: Optional warm sandbox factory for faster startup
        """
        self._db = db_client
        self._env_id = environment_id or self.DEFAULT_ENV_ID
        self._warm_factory = warm_factory
        
        # Track threads with sandbox creation/restart in progress
        self._pending_threads: Set[str] = set()
        # Cache of ready sandboxes for quick lookup
        self._ready_sandboxes: Dict[str, Sandbox] = {}
    
    async def _build_claim_config(
        self, 
        thread_id: str, 
        sandbox_id: str
    ) -> Dict[str, Any]:
        """
        Build the claim config for a sandbox from thread and related data.
        
        The claim config includes environment variables that the sandbox
        notebook/shell need to operate properly. Values are fetched from:
        - thread: user_id, kafka_profile_id
        - kafka_profiles: memory_dsn
        - profiles: openai_pk_virtual_key
        - vm_api_keys: api_key (vm_api_key)
        
        Args:
            thread_id: Thread ID
            sandbox_id: Sandbox ID being claimed
            
        Returns:
            Dict with 'config' key containing environment variables
        """
        # Get thread config with related data (kafka_profile, profile, vm_api_key)
        thread_config = await self._db.get_thread_config(thread_id)
        
        if thread_config:
            user_id = thread_config.get("user_id") or ""
            kafka_profile_id = thread_config.get("kafka_profile_id") or ""
            memory_dsn = thread_config.get("memory_dsn") or ""
            openai_pk_virtual_key = thread_config.get("openai_pk_virtual_key") or ""
            vm_api_key = thread_config.get("vm_api_key") or ""
        else:
            # Fallback to metadata for local DB or missing data
            thread_data = await self._db.get_thread_metadata(thread_id)
            metadata = (thread_data.get("metadata") or {}) if thread_data else {}
            user_id = metadata.get("user_id", "") if metadata else ""
            kafka_profile_id = metadata.get("kafka_profile_id", "") if metadata else ""
            memory_dsn = ""
            openai_pk_virtual_key = ""
            vm_api_key = ""
        
        # Build notebook environment config
        # Values from DB take precedence, fall back to env vars for local dev
        notebook_env = {
            "EXEC_DIR": os.path.dirname(os.path.abspath(__file__)),
            "PROXY_BASE_URL": "https://kafka-vm-proxy.onrender.com",
            "VM_API_KEY": vm_api_key or os.getenv("VM_API_KEY", "vm_dev_1234"),
            "OPENAI_PK_VIRTUAL_KEY": openai_pk_virtual_key or os.getenv("OPENAI_PK_VIRTUAL_KEY", ""),
            "USER_ID": str(user_id) if user_id else "",
            "KAFKA_PROFILE_ID": str(kafka_profile_id) if kafka_profile_id else "",
            "THREAD_ID": thread_id,
            "DEV": os.getenv("DEV", "false"),
            "DAYTONA_SANDBOX_ID": sandbox_id,
            "MEMORY_DB_DSN": memory_dsn or os.getenv("MEMORY_DSN", ""),
        }
        
        return {"config": notebook_env}
    
    async def get_sandbox_if_ready(self, thread_id: str) -> Optional[Sandbox]:
        """
        Get sandbox immediately if available and healthy, otherwise None.
        
        This is a quick non-blocking check. Use this when you want to use
        a sandbox if available but don't want to wait for creation.
        Also checks if sandbox is claimed and claims it if not.
        
        Args:
            thread_id: The thread ID to check
            
        Returns:
            Sandbox if ready, None if not available or not healthy
        """
        # Check cache first
        if thread_id in self._ready_sandboxes:
            sandbox = self._ready_sandboxes[thread_id]
            health_status = await sandbox.get_health_status()
            if health_status and health_status.get("healthy"):
                # Check if claimed, claim if not
                if not health_status.get("claimed", False):
                    print(f"📋 Sandbox {sandbox.id} not claimed, claiming now...")
                    claim_config = await self._build_claim_config(thread_id, sandbox.id)
                    try:
                        claim_result = await sandbox.claim(claim_config)
                        print(f"📋 Claim result: {claim_result}")
                    except Exception as e:
                        print(f"⚠️ Failed to claim sandbox {sandbox.id}: {e}")
                return sandbox
            # Cache stale, remove it
            del self._ready_sandboxes[thread_id]
        
        # Check if sandbox exists in DB
        sandbox_id = await self._db.get_thread_sandbox_id(thread_id)
        if sandbox_id is None:
            return None
        
        # Connect and check health (quick, non-blocking)
        try:
            sandbox = await DaytonaSandbox.connect(sandbox_id, self._env_id)
            health_status = await sandbox.get_health_status()
            if health_status and health_status.get("healthy"):
                # Check if claimed, claim if not
                if not health_status.get("claimed", False):
                    print(f"📋 Sandbox {sandbox.id} not claimed, claiming now...")
                    claim_config = await self._build_claim_config(thread_id, sandbox_id)
                    try:
                        claim_result = await sandbox.claim(claim_config)
                        print(f"📋 Claim result: {claim_result}")
                    except Exception as e:
                        print(f"⚠️ Failed to claim sandbox {sandbox_id}: {e}")
                self._ready_sandboxes[thread_id] = sandbox
                return sandbox
        except Exception:
            pass
        
        return None
    
    async def get_or_create_sandbox_ref(self, thread_id: str) -> Sandbox:
        """
        Get a sandbox reference for this thread (may not be healthy yet).
        
        Returns a sandbox object that tools can use - they have built-in
        health waits so they'll block when called if sandbox isn't ready.
        
        If background task is creating sandbox, waits briefly for ID to appear.
        ID creation is fast (happens before health wait), so this is quick.
        
        Args:
            thread_id: The thread ID
            
        Returns:
            Sandbox reference (may not be healthy yet)
        """
        # Check cache first
        if thread_id in self._ready_sandboxes:
            return self._ready_sandboxes[thread_id]
        
        # If background task is creating, wait briefly for ID (creation is fast)
        if thread_id in self._pending_threads:
            for _ in range(50):  # Wait up to 5s (50 * 100ms) for ID
                sandbox_id = await self._db.get_thread_sandbox_id(thread_id)
                if sandbox_id:
                    return await DaytonaSandbox.connect(sandbox_id, self._env_id)
                await asyncio.sleep(0.1)  # Check every 100ms
            raise RuntimeError(f"Timeout waiting for sandbox ID for thread {thread_id}")
        
        # Check DB for existing sandbox_id
        sandbox_id = await self._db.get_thread_sandbox_id(thread_id)
        
        if sandbox_id:
            # Have an ID, just connect (don't check health)
            return await DaytonaSandbox.connect(sandbox_id, self._env_id)
        
        # No sandbox and no background task - shouldn't happen normally
        # but create one just in case (fast, just creates - no health wait)
        print(f"📦 Creating sandbox reference for thread {thread_id}")
        sandbox = await DaytonaSandbox.create(self._env_id)
        await self._db.update_thread_sandbox_id(thread_id, sandbox.id)
        print(f"✅ Created sandbox {sandbox.id} for thread {thread_id}")
        
        return sandbox
    
    def is_sandbox_pending(self, thread_id: str) -> bool:
        """Check if sandbox creation/restart is in progress for this thread."""
        return thread_id in self._pending_threads
    
    def ensure_sandbox_background(
        self,
        thread_id: str
    ) -> None:
        """
        Start sandbox creation/restart in background if not already pending.
        
        This returns immediately. Use get_sandbox_if_ready() later to check
        if the sandbox is ready.
        
        Claim config is built automatically from thread metadata.
        
        Args:
            thread_id: The thread ID to create/restart sandbox for
        """
        if thread_id in self._pending_threads:
            print(f"⏳ Sandbox already being prepared for thread {thread_id}")
            return
        
        print(f"🚀 Starting background sandbox setup for thread {thread_id}")
        self._pending_threads.add(thread_id)
        
        # Fire and forget - will update cache when done
        asyncio.create_task(self._ensure_sandbox_task(thread_id))
    
    async def _ensure_sandbox_task(
        self,
        thread_id: str
    ) -> None:
        """Background task to create/restart sandbox and make it ready."""
        try:
            # First, ensure we have a sandbox ID in DB quickly
            sandbox_id = await self._db.get_thread_sandbox_id(thread_id)
            
            if sandbox_id is None:
                # Create sandbox (fast) and save ID immediately
                print(f"📦 [BG] Creating sandbox for thread {thread_id}")
                sandbox = await DaytonaSandbox.create(self._env_id)
                await self._db.update_thread_sandbox_id(thread_id, sandbox.id)
                print(f"✅ [BG] Sandbox {sandbox.id} created for thread {thread_id}")
            else:
                sandbox = await DaytonaSandbox.connect(sandbox_id, self._env_id)
            
            # Now wait for health and claim (slow part)
            print(f"⏳ [BG] Waiting for sandbox {sandbox.id} to be healthy...")
            await sandbox.wait_until_live()
            
            # Build claim config from thread metadata
            claim_config = await self._build_claim_config(thread_id, sandbox.id)
            print(f"📋 [BG] Claiming sandbox {sandbox.id} with config: {claim_config}")
            claim_result = await sandbox.claim(claim_config)
            print(f"📋 [BG] Claim result: {claim_result}")
            
            self._ready_sandboxes[thread_id] = sandbox
            print(f"✅ [BG] Sandbox {sandbox.id} ready for thread {thread_id}")
        except Exception as e:
            print(f"❌ [BG] Sandbox setup failed for thread {thread_id}: {e}")
        finally:
            self._pending_threads.discard(thread_id)
    
    async def ensure_sandbox(
        self,
        thread_id: str
    ) -> Sandbox:
        """
        Ensure a sandbox is ready for this thread (BLOCKING).
        
        Handles all three lifecycle cases automatically.
        For non-blocking operation, use ensure_sandbox_background() instead.
        
        Claim config is built automatically from thread metadata.
        
        Args:
            thread_id: The thread ID to get/create sandbox for
            
        Returns:
            Sandbox: A ready-to-use sandbox instance
        """
        # Check cache first
        if thread_id in self._ready_sandboxes:
            sandbox = self._ready_sandboxes[thread_id]
            if await sandbox.check_health():
                return sandbox
            del self._ready_sandboxes[thread_id]
        
        # Get thread's current sandbox_id from DB
        sandbox_id = await self._db.get_thread_sandbox_id(thread_id)
        print(f"🔍 ensure_sandbox: thread={thread_id}, existing_sandbox_id={sandbox_id}")
        
        if sandbox_id is None:
            # CASE 1: New thread, no sandbox yet
            print(f"📦 CASE 1: Creating new sandbox for thread {thread_id}")
            sandbox = await self._create_and_claim(thread_id)
            self._ready_sandboxes[thread_id] = sandbox
            return sandbox
        
        # Have a sandbox_id, check if it's alive
        sandbox = await DaytonaSandbox.connect(sandbox_id, self._env_id)
        print(f"🔗 Connected to existing sandbox {sandbox_id}, checking health...")
        
        if await sandbox.check_health():
            # CASE 2: Already running and healthy - just return it
            print(f"✅ CASE 2: Sandbox {sandbox_id} is healthy, reusing")
            self._ready_sandboxes[thread_id] = sandbox
            return sandbox
        
        # Not healthy - could be still starting up or actually stopped
        # Try waiting for it to become healthy first
        print(f"⏳ Sandbox {sandbox_id} not healthy yet, waiting for it...")
        try:
            await sandbox.wait_until_live(timeout=60)  # Wait up to 60s
            print(f"✅ Sandbox {sandbox_id} is now healthy")
            self._ready_sandboxes[thread_id] = sandbox
            return sandbox
        except (TimeoutError, Exception) as e:
            print(f"⚠️ Sandbox {sandbox_id} failed to become healthy: {e}")
        
        # CASE 3: Sandbox stopped/expired - need to restart
        print(f"🔄 CASE 3: Restarting sandbox for thread {thread_id}")
        sandbox = await self._restart_and_claim(thread_id, sandbox_id)
        self._ready_sandboxes[thread_id] = sandbox
        return sandbox
    
    async def _create_and_claim(
        self,
        thread_id: str
    ) -> Sandbox:
        """
        Create a new sandbox, save ID to DB, wait for live, and claim.
        
        Tries warm pool first for faster startup, falls back to creating new.
        """
        sandbox: Sandbox
        
        # Try warm pool first if available
        if self._warm_factory:
            warm_id = await self._warm_factory.get_warm_sandbox(self._env_id)
            if warm_id:
                sandbox = await DaytonaSandbox.connect(warm_id, self._env_id)
                print(f"✅ Claimed warm sandbox {warm_id} for thread {thread_id}")
            else:
                # No warm sandbox available, create new one
                print(f"⏳ No warm sandbox available, creating new for thread {thread_id}")
                sandbox = await DaytonaSandbox.create(self._env_id)
                print(f"✅ Created new sandbox {sandbox.id} for thread {thread_id}")
        else:
            # No warm factory, create new sandbox
            print(f"⏳ Creating new sandbox for thread {thread_id}")
            sandbox = await DaytonaSandbox.create(self._env_id)
            print(f"✅ Created sandbox {sandbox.id} for thread {thread_id}")
        
        # Save sandbox_id to thread in DB
        await self._db.update_thread_sandbox_id(thread_id, sandbox.id)
        
        # Wait for sandbox to be ready
        await sandbox.wait_until_live()
        
        # Build claim config from thread metadata and claim
        claim_config = await self._build_claim_config(thread_id, sandbox.id)
        print(f"📋 Claiming sandbox {sandbox.id} with config: {claim_config}")
        claim_result = await sandbox.claim(claim_config)
        print(f"📋 Claim result: {claim_result}")
        
        return sandbox
    
    async def _restart_and_claim(
        self,
        thread_id: str,
        sandbox_id: str
    ) -> Sandbox:
        """
        Restart a stopped sandbox, update DB if ID changed, and reclaim.
        """
        # Restart the sandbox (may return same or new ID)
        sandbox = await DaytonaSandbox.restart_sandbox(sandbox_id, self._env_id)
        
        # If sandbox_id changed, update DB
        if sandbox.id != sandbox_id:
            await self._db.update_thread_sandbox_id(thread_id, sandbox.id)
        
        # Wait for sandbox to be ready
        await sandbox.wait_until_live()
        
        # Build claim config from thread metadata and reclaim
        claim_config = await self._build_claim_config(thread_id, sandbox.id)
        await sandbox.claim(claim_config)
        
        return sandbox
    
    async def release_sandbox(self, thread_id: str) -> None:
        """
        Release/stop a thread's sandbox.
        
        Call this when a thread is done and sandbox should be released.
        
        Args:
            thread_id: The thread ID whose sandbox to release
        """
        sandbox_id = await self._db.get_thread_sandbox_id(thread_id)
        
        if sandbox_id:
            sandbox = await DaytonaSandbox.connect(sandbox_id, self._env_id)
            await sandbox.stop()
