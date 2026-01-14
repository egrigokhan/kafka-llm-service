"""
Supabase Client for Thread Message Storage
==========================================

This module handles all database interactions for thread-based conversations.
Messages are stored in Supabase and retrieved when users make API calls,
so they don't need to send the full conversation history.

Database Schema (expected):
--------------------------
Table: threads
    - id: UUID (primary key)
    - created_at: timestamp
    - metadata: JSONB (optional thread metadata)

Table: messages
    - id: UUID (primary key)
    - thread_id: UUID (foreign key to threads)
    - role: text ('system', 'user', 'assistant', 'tool')
    - content: text
    - name: text (optional)
    - tool_calls: JSONB (optional)
    - tool_call_id: text (optional)
    - created_at: timestamp
    - metadata: JSONB (optional message metadata)

Environment Variables:
    SUPABASE_URL: Your Supabase project URL
    SUPABASE_KEY: Your Supabase anon/service key
"""

import os
import uuid
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from supabase import create_client, Client

from src.llm.base import Message


class SupabaseClient:
    """
    Client for managing thread messages in Supabase.
    
    This client handles:
    - Retrieving messages for a thread
    - Saving new messages to a thread
    - Creating new threads
    
    Thread-based architecture means users only send new messages,
    and the server reconstructs the full conversation from the database.
    
    Example:
        >>> client = SupabaseClient()
        >>> 
        >>> # Get all messages for a thread
        >>> messages = await client.get_thread_messages("thread-uuid-here")
        >>> 
        >>> # Add a new message
        >>> await client.add_message("thread-uuid", Message(role="user", content="Hi"))
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        messages_table: str = "oai_messages",
        threads_table: str = "threads"
    ):
        """
        Initialize the Supabase client.
        
        Args:
            url: Supabase project URL. Falls back to SUPABASE_URL env var.
            key: Supabase API key. Falls back to SUPABASE_KEY env var.
            messages_table: Name of the messages table (default: "messages")
            threads_table: Name of the threads table (default: "threads")
        
        Raises:
            ValueError: If URL or key are not provided and not in environment.
        """
        self.url = url or os.environ.get("SUPABASE_URL")
        self.key = key or os.environ.get("SUPABASE_KEY")
        
        if not self.url:
            raise ValueError(
                "Supabase URL required. Pass url or set SUPABASE_URL env var."
            )
        if not self.key:
            raise ValueError(
                "Supabase key required. Pass key or set SUPABASE_KEY env var."
            )
        
        self.messages_table = messages_table
        self.threads_table = threads_table
        
        # Initialize Supabase client
        self.client: Client = create_client(self.url, self.key)
    
    async def get_thread_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
        include_system: bool = True
    ) -> List[Message]:
        """
        Retrieve all messages for a thread, ordered by creation time.
        
        Args:
            thread_id: UUID of the thread to retrieve messages for
            limit: Maximum number of messages to return (None = all)
            include_system: Whether to include system messages (default: True)
        
        Returns:
            List of Message objects, ordered from oldest to newest.
            Empty list if thread doesn't exist or has no messages.
        
        Example:
            >>> messages = await client.get_thread_messages("abc-123")
            >>> for msg in messages:
            ...     print(f"{msg.role}: {msg.content[:50]}...")
        """
        # Build query
        query = (
            self.client
            .table(self.messages_table)
            .select("*")
            .eq("thread_id", thread_id)
            .order("created_at", desc=False)
        )
        
        if not include_system:
            query = query.neq("role", "system")
        
        if limit:
            query = query.limit(limit)
        
        # Execute query (Supabase Python client is sync, but we wrap for consistency)
        response = query.execute()
        
        # Convert to Message objects
        # oai_messages table stores the message data in a "message" column as JSON
        messages = []
        for row in response.data:
            # The message column contains the full message object
            msg_data = row.get("message", row)  # fallback to row if no message column
            
            # Handle if msg_data is a string (JSON string) vs dict
            if isinstance(msg_data, str):
                import json
                msg_data = json.loads(msg_data)
            
            # Extract content - handle both string and OpenAI multi-part format
            content = msg_data.get("content")
            if isinstance(content, list):
                # Multi-part content format: [{"text": "...", "type": "text"}, ...]
                # Extract and concatenate all text parts
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                content = "\n".join(text_parts) if text_parts else None
            
            msg = Message(
                role=msg_data.get("role", "user"),
                content=content,
                name=msg_data.get("name"),
                tool_calls=msg_data.get("tool_calls"),
                tool_call_id=msg_data.get("tool_call_id")
            )
            messages.append(msg)
        
        return messages
    
    async def add_message(
        self,
        thread_id: str,
        message: Message,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add a new message to a thread.
        
        Args:
            thread_id: UUID of the thread to add the message to
            message: The Message object to add
            metadata: Optional additional metadata to store with the message
        
        Returns:
            Dict containing the inserted row data (includes generated id, created_at)
        
        Raises:
            Exception: If the insert fails (e.g., invalid thread_id)
        
        Example:
            >>> msg = Message(role="assistant", content="Hello! How can I help?")
            >>> result = await client.add_message("thread-123", msg)
            >>> print(f"Message ID: {result['id']}")
        """
        # Build the message object to store in the "message" column
        msg_obj = {
            "role": message.role,
            "content": message.content,
        }
        
        # Add optional fields to message object
        if message.name:
            msg_obj["name"] = message.name
        if message.tool_calls:
            msg_obj["tool_calls"] = message.tool_calls
        if message.tool_call_id:
            msg_obj["tool_call_id"] = message.tool_call_id
        
        # Build insert data - store message in "message" column
        data = {
            "id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "message": msg_obj,
        }
        
        if metadata:
            data["metadata"] = metadata
        
        # Insert into database
        response = (
            self.client
            .table(self.messages_table)
            .insert(data)
            .execute()
        )
        
        return response.data[0] if response.data else {}
    
    async def add_messages(
        self,
        thread_id: str,
        messages: List[Message]
    ) -> List[Dict[str, Any]]:
        """
        Add multiple messages to a thread in a single batch.
        
        More efficient than calling add_message repeatedly.
        
        Args:
            thread_id: UUID of the thread
            messages: List of Message objects to add
        
        Returns:
            List of inserted row data
        """
        if not messages:
            return []
        
        # Build batch insert data - store message in "message" column
        data = []
        for message in messages:
            msg_obj = {
                "role": message.role,
                "content": message.content,
            }
            if message.name:
                msg_obj["name"] = message.name
            if message.tool_calls:
                msg_obj["tool_calls"] = message.tool_calls
            if message.tool_call_id:
                msg_obj["tool_call_id"] = message.tool_call_id
            
            row = {
                "id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "message": msg_obj,
            }
            data.append(row)
        
        # Batch insert
        response = (
            self.client
            .table(self.messages_table)
            .insert(data)
            .execute()
        )
        
        return response.data or []
    
    async def create_thread(
        self,
        thread_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        system_message: Optional[str] = None,
        user_id: Optional[str] = None,
        kafka_profile_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new thread.
        
        Args:
            thread_id: Optional specific UUID for the thread.
                      If not provided, Supabase will generate one.
            metadata: Optional metadata to store with the thread (if table supports it)
            system_message: Optional system message to initialize the thread with
            user_id: Optional user ID to associate with the thread
            kafka_profile_id: Optional kafka profile ID to associate with the thread
        
        Returns:
            Dict containing the created thread data (id, created_at, etc.)
        
        Example:
            >>> thread = await client.create_thread(
            ...     system_message="You are a helpful coding assistant."
            ... )
            >>> print(f"Created thread: {thread['id']}")
        """
        # Build thread data - always provide an id (table requires non-null)
        data: Dict[str, Any] = {
            "id": thread_id or str(uuid.uuid4())
        }
        
        # Add user_id and kafka_profile_id as direct columns (not in metadata)
        if user_id:
            data["user_id"] = user_id
        if kafka_profile_id:
            data["kafka_profile_id"] = kafka_profile_id
        
        # Note: metadata column may not exist in all thread table schemas
        # Only include if explicitly provided and non-empty
        # If you need metadata support, ensure the column exists in Supabase
        
        # Insert thread
        response = (
            self.client
            .table(self.threads_table)
            .insert(data)
            .execute()
        )
        
        thread = response.data[0] if response.data else {}
        
        # Add system message if provided
        if system_message and thread.get("id"):
            await self.add_message(
                thread["id"],
                Message(role="system", content=system_message)
            )
        
        return thread
    
    async def thread_exists(self, thread_id: str) -> bool:
        """
        Check if a thread exists.
        
        Args:
            thread_id: UUID of the thread to check
        
        Returns:
            True if the thread exists, False otherwise
        """
        response = (
            self.client
            .table(self.threads_table)
            .select("id")
            .eq("id", thread_id)
            .execute()
        )
        
        return len(response.data) > 0
    
    async def get_thread_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a thread.
        
        Args:
            thread_id: UUID of the thread
        
        Returns:
            Thread metadata dict, or None if thread doesn't exist
        """
        response = (
            self.client
            .table(self.threads_table)
            .select("*")
            .eq("id", thread_id)
            .execute()
        )
        
        if response.data:
            return response.data[0]
        return None
    
    async def delete_thread_messages(self, thread_id: str) -> int:
        """
        Delete all messages in a thread (but keep the thread itself).
        
        Args:
            thread_id: UUID of the thread
        
        Returns:
            Number of messages deleted
        """
        response = (
            self.client
            .table(self.messages_table)
            .delete()
            .eq("thread_id", thread_id)
            .execute()
        )
        
        return len(response.data) if response.data else 0

    async def get_thread_sandbox_id(self, thread_id: str) -> Optional[str]:
        """
        Get the sandbox_id for a thread.
        
        Args:
            thread_id: UUID of the thread
        
        Returns:
            The sandbox_id if set, None otherwise
        """
        response = (
            self.client
            .table(self.threads_table)
            .select("sandbox_id")
            .eq("id", thread_id)
            .execute()
        )
        
        if response.data:
            return response.data[0].get("sandbox_id")
        return None
    
    async def update_thread_sandbox_id(
        self,
        thread_id: str,
        sandbox_id: str
    ) -> Dict[str, Any]:
        """
        Update the sandbox_id for a thread.
        
        Args:
            thread_id: UUID of the thread
            sandbox_id: The sandbox ID to associate with this thread
        
        Returns:
            Dict containing the updated thread data
        """
        response = (
            self.client
            .table(self.threads_table)
            .update({"sandbox_id": sandbox_id})
            .eq("id", thread_id)
            .execute()
        )
        
        return response.data[0] if response.data else {}
    
    async def get_thread_config(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get thread configuration data including related kafka_profile, profile, and vm_api_key.
        
        This fetches all the data needed for sandbox claim configuration and LLM provider:
        - thread: user_id, kafka_profile_id, vm_api_key_id
        - kafka_profiles: memory_dsn, user_id (to get profile), global_prompt
        - profiles: provider-specific virtual keys (via kafka_profiles.user_id)
        - vm_api_keys: api_key
        
        Args:
            thread_id: UUID of the thread
            
        Returns:
            Dict with thread config including:
            - thread_id
            - user_id
            - kafka_profile_id
            - memory_dsn (from kafka_profiles)
            - global_prompt (from kafka_profiles)
            - openai_pk_virtual_key (from profiles) - OpenAI virtual key
            - anthropic_pk_virtual_key (from profiles) - Anthropic virtual key
            - gemini_pk_virtual_key (from profiles) - Gemini virtual key
            - bedrock_pk_virtual_key (from profiles) - Bedrock virtual key
            - vm_api_key (from vm_api_keys)
        """
        # Step 1: Fetch thread with kafka_profiles and vm_api_keys
        # Note: profiles is accessed via kafka_profiles.user_id, not directly from threads
        response = (
            self.client
            .table(self.threads_table)
            .select(
                "id, user_id, kafka_profile_id, vm_api_key_id, "
                "kafka_profiles!threads_kp_fkey(user_id, memory_dsn, global_prompt), "
                "vm_api_keys!threads_vm_api_key_id_fkey(api_key)"
            )
            .eq("id", thread_id)
            .execute()
        )
        
        if not response.data:
            return None
        
        row = response.data[0]
        
        # Extract nested data
        kafka_profile = row.get("kafka_profiles") or {}
        vm_api_key_data = row.get("vm_api_keys") or {}
        
        # Step 2: Get provider-specific virtual keys from profiles via kafka_profile's user_id
        # Profiles has separate virtual keys for each provider: openai, anthropic, gemini, bedrock
        openai_pk_virtual_key = None
        anthropic_pk_virtual_key = None
        gemini_pk_virtual_key = None
        bedrock_pk_virtual_key = None
        kp_user_id = kafka_profile.get("user_id")
        if kp_user_id:
            profile_response = (
                self.client
                .table("profiles")
                .select("openai_pk_virtual_key, anthropic_pk_virtual_key, gemini_pk_virtual_key, bedrock_pk_virtual_key")
                .eq("id", kp_user_id)
                .execute()
            )
            if profile_response.data:
                profile_data = profile_response.data[0]
                openai_pk_virtual_key = profile_data.get("openai_pk_virtual_key")
                anthropic_pk_virtual_key = profile_data.get("anthropic_pk_virtual_key")
                gemini_pk_virtual_key = profile_data.get("gemini_pk_virtual_key")
                bedrock_pk_virtual_key = profile_data.get("bedrock_pk_virtual_key")
        
        return {
            "thread_id": row.get("id"),
            "user_id": row.get("user_id"),
            "kafka_profile_id": row.get("kafka_profile_id"),
            "memory_dsn": kafka_profile.get("memory_dsn"),
            "global_prompt": kafka_profile.get("global_prompt"),
            # Provider-specific virtual keys
            "openai_pk_virtual_key": openai_pk_virtual_key,
            "anthropic_pk_virtual_key": anthropic_pk_virtual_key,
            "gemini_pk_virtual_key": gemini_pk_virtual_key,
            "bedrock_pk_virtual_key": bedrock_pk_virtual_key,
            "vm_api_key": vm_api_key_data.get("api_key"),
        }
    
    async def get_or_create_vm_api_key(
        self, 
        thread_id: str, 
        user_id: str, 
        kafka_profile_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Get existing VM API key or create a new one for the thread.
        
        The VM API key is created when making the sandbox, so this method
        checks for an existing active key first, and creates one if needed.
        
        Args:
            thread_id: The thread ID
            user_id: The user ID (for team threads, should be team owner's user_id)
            kafka_profile_id: Optional kafka profile ID
            
        Returns:
            Tuple of (vm_api_key, vm_api_key_id) or (None, None) if creation fails
        """
        if not thread_id or not user_id:
            # Fallback to generated key for local dev
            return f"vm_{str(uuid.uuid4())}", None
        
        try:
            # Check for existing active key
            response = (
                self.client
                .table("vm_api_keys")
                .select("*")
                .eq("thread_id", thread_id)
                .eq("status", "active")
                .execute()
            )
            
            if response.data and len(response.data) > 0:
                # Return existing key
                return response.data[0]["api_key"], response.data[0]["id"]
            
            # No existing key, create a new one
            return await self._create_vm_api_key(thread_id, user_id, kafka_profile_id)
        except Exception as e:
            print(f"⚠️ Error getting/creating VM API key: {e}")
            # Fallback to generated key
            return f"vm_{str(uuid.uuid4())}", None
    
    async def _create_vm_api_key(
        self,
        thread_id: str,
        user_id: str,
        kafka_profile_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Create a new VM API key for the thread.
        
        Args:
            thread_id: The thread ID
            user_id: The user ID
            kafka_profile_id: Optional kafka profile ID
            
        Returns:
            Tuple of (vm_api_key, vm_api_key_id) or (None, None) if creation fails
        """
        try:
            # Get thread data to extract team_id if needed
            thread_response = (
                self.client
                .table(self.threads_table)
                .select("team_id, kafka_profile_id")
                .eq("id", thread_id)
                .execute()
            )
            
            thread_data = thread_response.data[0] if thread_response.data else {}
            team_id = thread_data.get("team_id")
            
            # Use kafka_profile_id from thread if not provided
            if not kafka_profile_id:
                kafka_profile_id = thread_data.get("kafka_profile_id")
            
            # If thread has a team, get team owner's user_id
            api_key_owner_id = user_id
            if team_id:
                team_response = (
                    self.client
                    .table("teams")
                    .select("created_by")
                    .eq("id", team_id)
                    .single()
                    .execute()
                )
                if team_response.data:
                    api_key_owner_id = team_response.data["created_by"]
            
            # Generate VM API key using database function
            key_response = self.client.rpc("generate_vm_api_key").execute()
            vm_api_key = key_response.data if key_response.data else f"vm_{str(uuid.uuid4())}"
            
            # Generate UUID for the new key
            key_id = str(uuid.uuid4())
            
            # Insert new API key
            insert_data = {
                "id": key_id,
                "thread_id": thread_id,
                "user_id": api_key_owner_id,
                "api_key": vm_api_key,
                "status": "active"
            }
            
            if team_id:
                insert_data["team_id"] = team_id
            
            if kafka_profile_id:
                insert_data["kafka_profile_id"] = kafka_profile_id
            
            # Insert the key
            insert_response = (
                self.client
                .table("vm_api_keys")
                .insert(insert_data)
                .execute()
            )
            
            if insert_response.data:
                # Update thread with vm_api_key_id
                self.client.table(self.threads_table).update({
                    "vm_api_key_id": key_id
                }).eq("id", thread_id).execute()
                
                return vm_api_key, key_id
            
            return None, None
        except Exception as e:
            print(f"⚠️ Error creating VM API key: {e}")
            # Fallback to generated key
            return f"vm_{str(uuid.uuid4())}", None
    
    async def get_playbooks_for_kafka_profile(
        self,
        kafka_profile_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all playbooks for a kafka profile.
        
        Args:
            kafka_profile_id: UUID of the kafka profile
            
        Returns:
            List of playbook dicts with id, name, and description
        """
        try:
            response = (
                self.client
                .table("playbooks")
                .select("id, name, description")
                .eq("kafka_profile_id", kafka_profile_id)
                .order("created_at", desc=False)
                .execute()
            )
            
            return response.data or []
        except Exception as e:
            print(f"⚠️ Error fetching playbooks: {e}")
            return []