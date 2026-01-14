"""
Agent Base
==========

This module provides the Agent class that runs an LLM in a loop,
executing tools until the `idle` function is called.

The agent streams all events (LLM content, tool calls, tool results)
in OpenAI-compatible format.

Example:
-------
```python
from src.agents import Agent
from src.llm import PortkeyLLMProvider
from src.tools import AgentToolProvider

# Create providers
llm = PortkeyLLMProvider(model="gpt-4o")
tools = AgentToolProvider(tools=[my_tool])
await tools.connect()

# Create agent
agent = Agent(
    llm_provider=llm,
    tool_provider=tools,
    system_prompt="You are a helpful assistant."
)

# Run agent and stream events
async for event in agent.run([Message(role="user", content="Hello")]):
    print(event)
```
"""

import json
import uuid
import time
import logging
from typing import Optional, List, Dict, Any, AsyncGenerator

from typing import TYPE_CHECKING

from src.llm.base import LLMProvider
from src.llm.types import Message
from src.tools.base import ToolProvider
from src.tools.types import Tool
from src.llm.context_compaction import ContextCompactionProvider, is_context_length_error

if TYPE_CHECKING:
    from src.prompts.base import PromptProvider


class Agent:
    """
    An agent that runs an LLM in a loop until it calls `idle`.
    
    The agent:
    - Streams LLM responses in real-time (OpenAI format)
    - Executes tool calls and streams their results
    - Continues the loop until the `idle` tool is called
    - Internally adds the `idle` tool to signal completion
    
    Attributes:
        llm_provider: The LLM provider to use for completions
        tool_provider: The tool provider for executing tools
        system_prompt: Optional system prompt to prepend
        max_iterations: Maximum loop iterations (safety limit)
    """
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_provider: ToolProvider,
        system_prompt: Optional[str] = None,
        prompt_provider: Optional["PromptProvider"] = None,
        context_compaction_provider: Optional[ContextCompactionProvider] = None,
        max_iterations: int = 50,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the agent.
        
        Args:
            llm_provider: LLM provider for generating responses
            tool_provider: Tool provider for executing tools
            system_prompt: Optional system prompt (overrides prompt_provider)
            prompt_provider: Optional PromptProvider for system prompt generation.
                           If both system_prompt and prompt_provider are given,
                           system_prompt takes precedence.
            context_compaction_provider: Optional provider for handling context length errors
            max_iterations: Safety limit for loop iterations
            logger: Optional logger for debugging
        """
        self.llm_provider = llm_provider
        self.tool_provider = tool_provider
        self.prompt_provider = prompt_provider
        self.context_compaction_provider = context_compaction_provider
        self.max_iterations = max_iterations
        self.logger = logger or logging.getLogger(__name__)
        
        # Resolve system prompt: explicit string takes precedence over provider
        if system_prompt is not None:
            self.system_prompt = system_prompt
        elif prompt_provider is not None:
            self.system_prompt = prompt_provider.get_system_prompt()
        else:
            self.system_prompt = None
        
        # Add the idle tool internally
        self._add_idle_tool()
    
    def _add_idle_tool(self) -> None:
        """Add the idle tool that signals the agent loop should stop."""
        idle_tool = Tool(
            name="idle",
            description="Call this after using tools to signal you are done with your task. Only needed after tool usage, not for simple text responses.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Optional brief summary of what was accomplished"
                    }
                },
                "required": []
            },
            handler=lambda summary="": {"status": "idle", "summary": summary}
        )
        self.tool_provider.add_tool(idle_tool)
    
    def _message_to_dict(self, message: Message) -> Dict[str, Any]:
        """Convert a Message object to a dictionary for compaction."""
        result: Dict[str, Any] = {"role": message.role}
        
        if message.content is not None:
            result["content"] = message.content
        
        if message.tool_calls:
            result["tool_calls"] = message.tool_calls
        
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        
        if message.name:
            result["name"] = message.name
        
        return result
    
    def _dict_to_message(self, data: Dict[str, Any]) -> Message:
        """Convert a dictionary back to a Message object."""
        return Message(
            role=data.get("role", "user"),
            content=data.get("content"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )
    
    async def run(
        self,
        messages: List[Message],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run the agent loop, yielding streaming events.
        
        This method runs the LLM in a loop, executing tool calls until
        the `idle` function is called. All events are yielded in 
        OpenAI-compatible streaming format.
        
        Args:
            messages: Initial messages (conversation history)
            model: Model to use
            temperature: LLM temperature
            max_tokens: Max tokens per completion
            **kwargs: Additional LLM parameters
        
        Yields:
            Dict events in OpenAI streaming format:
            - Standard OpenAI stream chunks for LLM content
            - Custom "tool_result" events for tool execution
            - "agent_done" event when idle is called
        
        Example events:
            # LLM content chunk
            {"id": "...", "choices": [{"delta": {"content": "Hello"}}], ...}
            
            # Tool result
            {"type": "tool_result", "tool_call_id": "...", "delta": "...", "is_complete": True}
            
            # Agent done
            {"type": "agent_done", "reason": "idle", "summary": "..."}
        """
        # Prepend system prompt if provided and not already present
        working_messages = list(messages)
        if self.system_prompt:
            if not working_messages or working_messages[0].role != "system":
                working_messages.insert(0, Message(role="system", content=self.system_prompt))
        
        # Get all available tools
        tools = await self.tool_provider.get_tools()
        
        # Track if we've already attempted context compaction this run
        context_compaction_attempted = False
        
        for iteration in range(self.max_iterations):
            # Generate unique IDs for this completion
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            created = int(time.time())
            
            # Accumulate the response
            full_content = ""
            accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            
            # Stream the LLM completion with context length error handling
            try:
                stream = self.llm_provider.stream_completion(
                    working_messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
                # We need to iterate through the stream inside the try block
                # to catch errors that occur during streaming
                chunks_buffer = []
                async for chunk in stream:
                    chunks_buffer.append(chunk)
            except Exception as e:
                # Check if this is a context length error
                if is_context_length_error(e) and not context_compaction_attempted:
                    if self.context_compaction_provider:
                        self.logger.info(f"Context length error detected: {e}")
                        self.logger.info("Initiating context compaction...")
                        
                        # Convert messages to dict format for compaction
                        messages_dict = [self._message_to_dict(m) for m in working_messages]
                        
                        try:
                            compacted_messages = await self.context_compaction_provider.compact(
                                messages=messages_dict,
                                system_prompt=self.system_prompt or "",
                                model=model,
                            )
                            
                            # Convert back to Message objects
                            working_messages = [self._dict_to_message(m) for m in compacted_messages]
                            context_compaction_attempted = True
                            
                            self.logger.info(
                                f"Context compaction complete. Messages: {len(messages_dict)} -> {len(working_messages)}"
                            )
                            
                            # Retry this iteration with compacted messages
                            continue
                            
                        except Exception as compact_error:
                            self.logger.error(f"Context compaction failed: {compact_error}")
                            # Re-raise the original error
                            raise e
                    else:
                        self.logger.warning("Context length error but no compaction provider configured")
                        raise
                else:
                    # Not a context length error or already attempted compaction
                    raise
            
            # Process the buffered chunks
            for chunk in chunks_buffer:
                # Build OpenAI-format chunk
                delta: Dict[str, Any] = {}
                
                if chunk.role:
                    delta["role"] = chunk.role
                
                if chunk.content:
                    delta["content"] = chunk.content
                    full_content += chunk.content
                
                # Handle tool calls in streaming format
                if chunk.tool_calls:
                    delta["tool_calls"] = []
                    for tc in chunk.tool_calls:
                        idx = tc.get("index", 0)
                        
                        # Initialize or update accumulated tool call
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": ""
                                }
                            }
                        
                        # Accumulate arguments
                        if tc.get("function", {}).get("arguments"):
                            accumulated_tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]
                        
                        # Update id and name if provided
                        if tc.get("id"):
                            accumulated_tool_calls[idx]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            accumulated_tool_calls[idx]["function"]["name"] = tc["function"]["name"]
                        
                        # Preserve thought_signature for Gemini (required for multi-turn tool calling)
                        if tc.get("function", {}).get("thought_signature"):
                            accumulated_tool_calls[idx]["function"]["thought_signature"] = tc["function"]["thought_signature"]
                        
                        # Build delta for this tool call
                        tc_delta: Dict[str, Any] = {"index": idx}
                        if tc.get("id"):
                            tc_delta["id"] = tc["id"]
                            tc_delta["type"] = "function"
                        if tc.get("function"):
                            tc_delta["function"] = {}
                            if tc["function"].get("name"):
                                tc_delta["function"]["name"] = tc["function"]["name"]
                            if tc["function"].get("arguments"):
                                tc_delta["function"]["arguments"] = tc["function"]["arguments"]
                            # Include thought_signature in delta if present
                            if tc["function"].get("thought_signature"):
                                tc_delta["function"]["thought_signature"] = tc["function"]["thought_signature"]
                        
                        delta["tool_calls"].append(tc_delta)
                
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                
                # Yield the chunk in OpenAI format
                chunk_response = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason if chunk.finish_reason else None
                    }]
                }
                yield chunk_response
            
            # Convert accumulated tool calls to list
            tool_calls = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls.keys())]
            
            # If no tool calls, the LLM responded with just text - we're done
            if not tool_calls:
                # Yield agent done with the text content
                yield {
                    "type": "agent_done",
                    "reason": "text_response",
                    "final_content": full_content,
                    "iteration": iteration
                }
                return
            
            # Add assistant message with tool calls to context
            working_messages.append(Message(
                role="assistant",
                content=full_content if full_content else None,
                tool_calls=tool_calls
            ))
            
            # Execute each tool call
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]
                tool_call_id = tool_call["id"]
                
                # Parse arguments
                try:
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    tool_args = {}
                
                # Check for idle - signal completion
                if tool_name == "idle":
                    summary = tool_args.get("summary", "")
                    
                    # Add tool result to messages (for completeness)
                    working_messages.append(Message(
                        role="tool",
                        content=json.dumps({"status": "idle", "summary": summary}),
                        tool_call_id=tool_call_id,
                        name=tool_name
                    ))
                    
                    # Yield final tool result
                    yield {
                        "type": "tool_result",
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "delta": json.dumps({"status": "idle", "summary": summary}),
                        "is_complete": True
                    }
                    
                    # Yield agent done event
                    yield {
                        "type": "agent_done",
                        "reason": "idle",
                        "summary": summary,
                        "iteration": iteration
                    }
                    return
                
                # Execute the tool with streaming
                result_content = ""
                
                # Use streaming execution for all tools
                async for chunk in self.tool_provider.run_tool_stream(tool_name, tool_args, tool_call_id):
                    result_content += chunk.delta
                    yield {
                        "type": "tool_result",
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "delta": chunk.delta,
                        "is_complete": chunk.is_complete
                    }
                
                # Add tool result to messages
                working_messages.append(Message(
                    role="tool",
                    content=result_content,
                    tool_call_id=tool_call_id,
                    name=tool_name
                ))
        
        # Max iterations reached
        yield {
            "type": "agent_done",
            "reason": "max_iterations",
            "iteration": self.max_iterations
        }
