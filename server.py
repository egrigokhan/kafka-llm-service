"""
OpenAI-Compatible Chat Completions Server with Thread Support
=============================================================

This server provides an OpenAI-compatible API with thread-based conversations.

Endpoints:
---------
    POST /v1/threads/{thread_id}/chat/completions - Thread-based chat
    POST /v1/chat/completions - Standard stateless chat
    POST /v1/agent/run - Stateless agent run
    POST /v1/threads/{thread_id}/agent/run - Thread-based agent run

Usage:
-----
1. Set environment variables (see .env.example)
2. Run: uvicorn server:app --reload
3. Use with any OpenAI-compatible client
"""

import os
import json
import uuid
import time
from typing import Optional, List, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from server_tools.shell import ShellTools
from src.llm import Message
from src.db import SupabaseClient, LocalDBClient
from src.kafka import (
    KafkaV1Provider,
    ChatMessage,
    ChatCompletionRequest,
    AgentRunRequest,
    CreateThreadRequest,
    DeltaContent,
    StreamChoice,
    StreamChunkResponse,
    MessageContent,
    Choice,
    Usage,
    ChatCompletionResponse,
    convert_to_internal_message,
    sanitize_messages_for_openai,
)
from src.sandbox import LocalSandbox, SandboxManager, DaytonaSandbox, LazySandbox
from src.warm_sandbox.daytona import DaytonaWarmSandboxFactory

# Import server tools
from server_tools import get_weather_tool, count_tool, ShellTools, PlannerTools, NotebookTools, DEFAULT_MCP_SERVERS

# Load environment variables
load_dotenv()


# =============================================================================
# Global instances
# =============================================================================

# Shared Kafka provider (stateless mode - no thread_id)
kafka: Optional[KafkaV1Provider] = None

# DB client for stateless operations (Supabase)
db_client: Optional[SupabaseClient] = None

# Local DB client for thread-based operations (SQLite) - kept for local dev fallback
local_db: Optional[LocalDBClient] = None

# Thread DB client - points to db_client (Supabase) for production
thread_db: Optional[SupabaseClient] = None

# Local sandbox instance (for stateless/global kafka)
local_sandbox: Optional[LocalSandbox] = None

# Sandbox manager for thread-based Daytona sandboxes
sandbox_manager: Optional[SandboxManager] = None
warm_factory: Optional[DaytonaWarmSandboxFactory] = None

# Daytona sandbox environment for threads
DAYTONA_ENV_ID = "kafka-lite-vm-0.0.10"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI app.
    """
    global kafka, db_client, local_db, local_sandbox, sandbox_manager, warm_factory, thread_db
    
    # Initialize Supabase client - used for all thread operations
    db_client = SupabaseClient()
    
    # Use Supabase for thread operations (thread_db = db_client)
    thread_db = db_client
    
    # Initialize local SQLite DB (kept for local dev fallback if needed)
    local_db = LocalDBClient()
    await local_db.initialize()
    
    # Initialize local sandbox (for stateless/global kafka)
    sandbox_url = os.environ.get("LOCAL_SANDBOX_URL", "http://localhost:8081")
    local_sandbox = LocalSandbox(sandbox_url)
    
    # Initialize warm sandbox factory for Daytona (for thread-based requests)
    # Uses SupabaseClient (db_client) to fetch thread config (openai_pk_virtual_key, memory_dsn, vm_api_key)
    warm_factory = DaytonaWarmSandboxFactory()
    sandbox_manager = SandboxManager(
        db_client=db_client,  # Use Supabase for thread config
        environment_id=DAYTONA_ENV_ID,
        warm_factory=warm_factory
    )
    print(f"✅ SandboxManager initialized (env: {DAYTONA_ENV_ID})")
    
    # Create tools for global kafka (uses local sandbox)
    shell_tools = ShellTools(local_sandbox, health_timeout=30)
    notebook_tools = NotebookTools(local_sandbox, health_timeout=300)
    planner_tools = PlannerTools()
    
    # Initialize Kafka V1 provider with all tools
    # Note: notebook is now a SandboxTool for real-time streaming (not MCP)
    kafka = KafkaV1Provider(
        tools=[get_weather_tool, count_tool] + planner_tools.tools,
        sandbox_tools=shell_tools.tools + notebook_tools.tools,
        mcp_servers=DEFAULT_MCP_SERVERS
    )
    await kafka.initialize()
    
    # Log available tools
    available_tools = await kafka.get_tools()
    all_tool_names = [t["function"]["name"] for t in available_tools]
    
    print("✅ Server initialized with KafkaV1Provider")
    print(f"   Available tools ({len(all_tool_names)}): {all_tool_names}")
    
    yield
    
    # Cleanup
    if kafka:
        await kafka.cleanup()
    if local_sandbox:
        await local_sandbox.stop()
    if warm_factory:
        await warm_factory.close()
    print("👋 Server shutdown complete")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Kafka Agent API",
    description="OpenAI-compatible API with thread-based message history and agent capabilities",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# SSE Stream Generators
# =============================================================================

async def generate_agent_stream(
    messages: List[Message],
    model: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> AsyncGenerator[str, None]:
    """Generate SSE stream from Kafka agent run (stateless)."""
    if not kafka or not kafka.agent:
        yield f"data: {json.dumps({'error': 'Kafka not initialized'})}\n\n"
        return
    
    try:
        async for event in kafka.run(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            yield f"data: {json.dumps(event)}\n\n"
        
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'agent_error'}})}\n\n"
        yield "data: [DONE]\n\n"


async def generate_agent_stream_with_thread(
    thread_id: str,
    new_messages: List[Message],
    model: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> AsyncGenerator[str, None]:
    """Generate SSE stream from Kafka agent run with thread persistence using Daytona sandbox."""
    if not kafka or not thread_db or not sandbox_manager:
        yield f"data: {json.dumps({'error': 'Kafka, DB, or SandboxManager not initialized'})}\n\n"
        return
    
    try:
        # NON-BLOCKING: Check if sandbox is ready, kick off creation in background if not
        thread_sandbox = await sandbox_manager.get_sandbox_if_ready(thread_id)
        
        if thread_sandbox:
            print(f"✅ Sandbox ready for thread {thread_id}")
        else:
            # Kick off background creation
            print(f"⏳ No sandbox ready for thread {thread_id}, starting background setup")
            sandbox_manager.ensure_sandbox_background(thread_id=thread_id)
            # Use LazySandbox - it will wait for real sandbox only when a tool is called
            # This allows the LLM to start streaming immediately
            thread_sandbox = LazySandbox(thread_id, sandbox_manager, timeout=120.0)
            print(f"📦 Using LazySandbox for thread {thread_id} (tools will wait when called)")
        
        # Sandbox tools always included - they have built-in health waits
        thread_shell_tools = ShellTools(thread_sandbox, health_timeout=30)
        thread_notebook_tools = NotebookTools(thread_sandbox, health_timeout=300)
        planner_tools = PlannerTools()
        
        # Create thread-specific Kafka with all tools
        thread_kafka = KafkaV1Provider(
            thread_id=thread_id,
            tools=[get_weather_tool, count_tool] + planner_tools.tools,
            sandbox_tools=thread_shell_tools.tools + thread_notebook_tools.tools,
            mcp_servers=[],  # Don't reconnect MCP - we could share but skip for simplicity
            db_client=thread_db
        )
        
        await thread_kafka.initialize()
        
        async for event in thread_kafka.run_with_thread(
            new_messages=new_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            save_to_thread=True
        ):
            yield f"data: {json.dumps(event)}\n\n"
        
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'agent_error'}})}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        if 'thread_kafka' in dir():
            await thread_kafka.cleanup()


async def generate_completion_stream(
    messages: List[Message],
    request: ChatCompletionRequest,
    thread_id: Optional[str] = None
) -> AsyncGenerator[str, None]:
    """
    Generate SSE stream for chat completions.
    
    Uses the Kafka agent under the hood for tool execution.
    """
    if not kafka or not kafka.agent:
        yield f"data: {json.dumps({'error': 'Kafka not initialized'})}\n\n"
        return
    
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    model = request.model
    
    try:
        # Run agent and collect final response
        final_content = ""
        messages_to_save: List[Message] = []
        
        async for event in kafka.run(
            messages=messages,
            model=model,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens
        ):
            event_type = event.get("type")
            
            # Stream tool results
            if event_type == "tool_result":
                tool_data = {
                    "type": "tool_result",
                    "tool_call_id": event.get("tool_call_id"),
                    "tool_name": event.get("tool_name"),
                    "delta": event.get("delta", ""),
                    "is_complete": event.get("is_complete", False)
                }
                yield f"data: {json.dumps(tool_data)}\n\n"
                
            # Track assistant messages for saving
            elif event_type == "assistant_message":
                msg_data = event.get("message", {})
                if msg_data:
                    messages_to_save.append(Message(
                        role="assistant",
                        content=msg_data.get("content"),
                        tool_calls=msg_data.get("tool_calls")
                    ))
                    
            elif event_type == "tool_message":
                messages_to_save.append(Message(
                    role="tool",
                    content=event.get("content", ""),
                    tool_call_id=event.get("tool_call_id"),
                    name=event.get("tool_name")
                ))
                
            elif event_type == "agent_done":
                final_content = event.get("final_content", "")
        
        # Send intermediate messages for frontend
        if messages_to_save:
            tool_messages_data = {
                "type": "tool_messages",
                "messages": [msg.to_dict() for msg in messages_to_save]
            }
            yield f"data: {json.dumps(tool_messages_data)}\n\n"
        
        # Stream the final response
        first_chunk = StreamChunkResponse(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaContent(role="assistant"), finish_reason=None)]
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"
        
        # Stream content in chunks
        chunk_size = 20
        for i in range(0, len(final_content), chunk_size):
            chunk_text = final_content[i:i + chunk_size]
            chunk = StreamChunkResponse(
                id=completion_id,
                created=created,
                model=model,
                choices=[StreamChoice(delta=DeltaContent(content=chunk_text), finish_reason=None)]
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
        
        # Save to thread if provided
        if thread_id and thread_db:
            for msg in messages_to_save:
                await thread_db.add_message(thread_id, msg)
            if final_content:
                await thread_db.add_message(thread_id, Message(role="assistant", content=final_content))
        
        # Final chunk
        final_chunk = StreamChunkResponse(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaContent(), finish_reason="stop")]
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
        yield "data: [DONE]\n\n"


# =============================================================================
# API Endpoints
# =============================================================================

@app.post("/v1/threads/{thread_id}/chat/completions")
async def chat_completions(thread_id: str, request: ChatCompletionRequest):
    """Thread-based chat completions using Kafka agent with local SQLite."""
    if not kafka or not thread_db:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    # Ensure thread exists
    if not await thread_db.thread_exists(thread_id):
        await thread_db.create_thread(thread_id=thread_id)
    
    # Get history and convert new messages
    history = await thread_db.get_thread_messages(thread_id)
    new_messages = [convert_to_internal_message(m) for m in request.messages]
    
    # Save new user/system messages
    for msg in new_messages:
        if msg.role in ("user", "system"):
            await thread_db.add_message(thread_id, msg)
    
    # Combine and sanitize
    all_messages = sanitize_messages_for_openai(history + new_messages)
    
    if request.stream:
        return StreamingResponse(
            generate_completion_stream(all_messages, request, thread_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )
    else:
        # Non-streaming: collect full response
        final_content = ""
        messages_to_save: List[Message] = []
        
        async for event in kafka.run(
            messages=all_messages,
            model=request.model,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens
        ):
            if event.get("type") == "agent_done":
                final_content = event.get("final_content", "")
            elif event.get("type") == "assistant_message":
                msg_data = event.get("message", {})
                if msg_data:
                    messages_to_save.append(Message(
                        role="assistant",
                        content=msg_data.get("content"),
                        tool_calls=msg_data.get("tool_calls")
                    ))
            elif event.get("type") == "tool_message":
                messages_to_save.append(Message(
                    role="tool",
                    content=event.get("content", ""),
                    tool_call_id=event.get("tool_call_id"),
                    name=event.get("tool_name")
                ))
        
        # Save messages
        for msg in messages_to_save:
            await thread_db.add_message(thread_id, msg)
        if final_content:
            await thread_db.add_message(thread_id, Message(role="assistant", content=final_content))
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=request.model,
            choices=[Choice(message=MessageContent(content=final_content), finish_reason="stop")],
            usage=Usage()
        )


@app.post("/v1/chat/completions")
async def chat_completions_standard(request: ChatCompletionRequest):
    """Standard OpenAI-compatible stateless chat completions using Kafka agent."""
    if not kafka:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    messages = sanitize_messages_for_openai([convert_to_internal_message(m) for m in request.messages])
    
    if request.stream:
        return StreamingResponse(
            generate_completion_stream(messages, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )
    else:
        # Non-streaming
        final_content = ""
        
        async for event in kafka.run(
            messages=messages,
            model=request.model,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens
        ):
            if event.get("type") == "agent_done":
                final_content = event.get("final_content", "")
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=request.model,
            choices=[Choice(message=MessageContent(content=final_content), finish_reason="stop")],
            usage=Usage()
        )


@app.post("/v1/agent/run")
async def run_agent(request: AgentRunRequest):
    """Run the Kafka agent (stateless) until it calls idle."""
    if not kafka:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    messages = [convert_to_internal_message(m) for m in request.messages]
    
    return StreamingResponse(
        generate_agent_stream(messages, request.model, request.temperature, request.max_tokens),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@app.post("/v1/threads/{thread_id}/agent/run")
async def run_agent_with_thread(thread_id: str, request: AgentRunRequest):
    """Run the Kafka agent with thread-based message history (uses local SQLite)."""
    if not kafka or not thread_db:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    # Ensure thread exists
    if not await thread_db.thread_exists(thread_id):
        await thread_db.create_thread(thread_id=thread_id)
    
    new_messages = [convert_to_internal_message(m) for m in request.messages]
    
    return StreamingResponse(
        generate_agent_stream_with_thread(thread_id, new_messages, request.model, request.temperature, request.max_tokens),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


# =============================================================================
# Thread Management Endpoints
# =============================================================================

@app.post("/v1/threads/{thread_id}/messages")
async def add_message_to_thread(thread_id: str, message: ChatMessage):
    """Add a message to a thread (uses Supabase)."""
    if not thread_db:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    if not await thread_db.thread_exists(thread_id):
        await thread_db.create_thread(thread_id=thread_id)
    
    result = await thread_db.add_message(thread_id, convert_to_internal_message(message))
    return {"success": True, "message_id": result.get("id")}


@app.get("/v1/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str):
    """Get all messages in a thread (uses Supabase)."""
    if not thread_db:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    if not await thread_db.thread_exists(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    
    messages = await thread_db.get_thread_messages(thread_id)
    return {"thread_id": thread_id, "messages": [m.to_dict() for m in messages]}


@app.post("/v1/threads")
async def create_thread(request: Optional[CreateThreadRequest] = None):
    """
    Create a new thread (uses Supabase).
    
    Request body can include:
    - system_message: Optional starting system message
    - user_id: User ID for sandbox claiming
    - kafka_profile_id: Kafka profile ID for sandbox claiming
    - metadata: Additional metadata (not currently stored)
    """
    if not thread_db:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    # Extract fields from request
    system_message = None
    user_id = None
    kafka_profile_id = None
    
    if request:
        system_message = request.system_message
        user_id = request.user_id
        kafka_profile_id = request.kafka_profile_id
    
    thread = await thread_db.create_thread(
        system_message=system_message,
        user_id=user_id,
        kafka_profile_id=kafka_profile_id
    )
    return {"thread_id": thread.get("id"), "created_at": thread.get("created_at")}


@app.delete("/v1/threads/{thread_id}/messages")
async def clear_thread(thread_id: str):
    """Delete all messages in a thread (uses Supabase)."""
    if not thread_db:
        raise HTTPException(status_code=503, detail="Server not initialized")
    
    if not await thread_db.thread_exists(thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    
    deleted = await thread_db.delete_thread_messages(thread_id)
    return {"success": True, "deleted_count": deleted}


@app.get("/v1/models")
async def list_models():
    """List available models."""
    return {
        "object": "list",
        "data": [
            {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
            {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
            {"id": "gpt-4-turbo", "object": "model", "owned_by": "openai"},
            {"id": "gpt-3.5-turbo", "object": "model", "owned_by": "openai"},
            {"id": "claude-3-opus-20240229", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-3-sonnet-20240229", "object": "model", "owned_by": "anthropic"},
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "kafka_initialized": kafka is not None and kafka.is_initialized}


# =============================================================================
# Main entry point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)