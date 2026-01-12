"""
Local SQLite Client for Thread Message Storage
===============================================

Drop-in replacement for SupabaseClient using local SQLite.
Same interface, but uses aiosqlite for async SQLite operations.
"""

import os
import json
import uuid
import aiosqlite
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from src.llm.base import Message


class LocalDBClient:
    """
    SQLite-based client for managing thread messages locally.
    
    Same interface as SupabaseClient for easy swapping.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the SQLite client.
        
        Args:
            db_path: Path to SQLite database file. 
                    Defaults to LOCAL_DB_PATH env var or ./data/threads.db
        """
        self.db_path = db_path or os.environ.get(
            "LOCAL_DB_PATH", 
            str(Path(__file__).parent.parent.parent / "data" / "threads.db")
        )
        self._initialized = False
    
    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        if self._initialized:
            return
            
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        async with aiosqlite.connect(self.db_path) as db:
            # Create threads table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    sandbox_id TEXT
                )
            """)
            
            # Create messages table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (thread_id) REFERENCES threads(id)
                )
            """)
            
            # Create index for faster thread lookups
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_thread_id 
                ON messages(thread_id)
            """)
            
            await db.commit()
        
        self._initialized = True
    
    async def _ensure_initialized(self) -> None:
        """Ensure database is initialized before operations."""
        if not self._initialized:
            await self.initialize()
    
    async def get_thread_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
        include_system: bool = True
    ) -> List[Message]:
        """
        Retrieve all messages for a thread, ordered by creation time.
        """
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            query = """
                SELECT * FROM messages 
                WHERE thread_id = ? 
                ORDER BY created_at ASC
            """
            params = [thread_id]
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        
        messages = []
        for row in rows:
            msg_data = json.loads(row["message"])
            
            # Skip system messages if requested
            if not include_system and msg_data.get("role") == "system":
                continue
            
            # Handle multi-part content
            content = msg_data.get("content")
            if isinstance(content, list):
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
        """Add a new message to a thread."""
        await self._ensure_initialized()
        
        msg_id = str(uuid.uuid4())
        
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
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO messages (id, thread_id, message, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (msg_id, thread_id, json.dumps(msg_obj), json.dumps(metadata) if metadata else None)
            )
            await db.commit()
        
        return {"id": msg_id, "thread_id": thread_id}
    
    async def add_messages(
        self,
        thread_id: str,
        messages: List[Message]
    ) -> List[Dict[str, Any]]:
        """Add multiple messages to a thread in a single batch."""
        await self._ensure_initialized()
        
        if not messages:
            return []
        
        results = []
        async with aiosqlite.connect(self.db_path) as db:
            for message in messages:
                msg_id = str(uuid.uuid4())
                
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
                
                await db.execute(
                    """
                    INSERT INTO messages (id, thread_id, message)
                    VALUES (?, ?, ?)
                    """,
                    (msg_id, thread_id, json.dumps(msg_obj))
                )
                results.append({"id": msg_id, "thread_id": thread_id})
            
            await db.commit()
        
        return results
    
    async def create_thread(
        self,
        thread_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        system_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new thread."""
        await self._ensure_initialized()
        
        thread_id = thread_id or str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO threads (id, created_at, metadata)
                VALUES (?, ?, ?)
                """,
                (thread_id, created_at, json.dumps(metadata) if metadata else None)
            )
            await db.commit()
        
        thread = {"id": thread_id, "created_at": created_at, "metadata": metadata}
        
        # Add system message if provided
        if system_message:
            await self.add_message(
                thread_id,
                Message(role="system", content=system_message)
            )
        
        return thread
    
    async def thread_exists(self, thread_id: str) -> bool:
        """Check if a thread exists."""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM threads WHERE id = ?",
                (thread_id,)
            ) as cursor:
                row = await cursor.fetchone()
        
        return row is not None
    
    async def get_thread_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a thread."""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM threads WHERE id = ?",
                (thread_id,)
            ) as cursor:
                row = await cursor.fetchone()
        
        if row:
            return {
                "id": row["id"],
                "created_at": row["created_at"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
                "sandbox_id": row["sandbox_id"]
            }
        return None
    
    async def delete_thread_messages(self, thread_id: str) -> int:
        """Delete all messages in a thread (but keep the thread itself)."""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM messages WHERE thread_id = ?",
                (thread_id,)
            )
            deleted = cursor.rowcount
            await db.commit()
        
        return deleted
    
    async def get_thread_sandbox_id(self, thread_id: str) -> Optional[str]:
        """Get the sandbox_id for a thread."""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT sandbox_id FROM threads WHERE id = ?",
                (thread_id,)
            ) as cursor:
                row = await cursor.fetchone()
        
        if row:
            return row[0]
        return None
    
    async def update_thread_sandbox_id(
        self,
        thread_id: str,
        sandbox_id: str
    ) -> Dict[str, Any]:
        """Update the sandbox_id for a thread."""
        await self._ensure_initialized()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE threads SET sandbox_id = ? WHERE id = ?",
                (sandbox_id, thread_id)
            )
            await db.commit()
        
        return {"id": thread_id, "sandbox_id": sandbox_id}
    
    async def get_thread_config(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get thread configuration data for sandbox claim.
        
        For LocalDBClient, this returns None to signal that the caller
        should fall back to get_thread_metadata() and env vars.
        The full thread config (with kafka_profile, profile, vm_api_key joins)
        is only available via SupabaseClient.
        
        Args:
            thread_id: UUID of the thread
            
        Returns:
            None - local DB doesn't have related config data
        """
        return None