"""
Example Kafka V1 Agent
======================

Demonstrates how to create and use a KafkaV1Provider agent.
"""

import asyncio
from typing import Optional

from src.kafka import KafkaV1Provider
from src.llm import Message

from .tools import get_weather_tool, count_tool, DEFAULT_MCP_SERVERS


def create_example_agent(thread_id: Optional[str] = None) -> KafkaV1Provider:
    """
    Create an example Kafka V1 agent with weather and counting tools.
    
    Args:
        thread_id: Optional thread ID for persistent conversations
        
    Returns:
        Configured KafkaV1Provider instance (not yet initialized)
    """
    return KafkaV1Provider(
        thread_id=thread_id,
        tools=[get_weather_tool, count_tool],
        mcp_servers=DEFAULT_MCP_SERVERS
    )


async def run_example():
    """
    Run an example conversation with the Kafka agent.
    """
    # Create agent without thread (stateless)
    agent = create_example_agent()
    
    try:
        # Initialize
        await agent.initialize()
        
        print("\n" + "=" * 50)
        print("Kafka V1 Agent Example")
        print("=" * 50 + "\n")
        
        # Create a user message
        messages = [
            Message(role="user", content="What's the weather like in Tokyo?")
        ]
        
        print(f"User: {messages[0].content}\n")
        print("Agent response:")
        print("-" * 30)
        
        # Run the agent
        async for event in agent.run(
            messages=messages,
            model="gpt-4o",
            temperature=0.7
        ):
            # Handle different event types
            event_type = event.get("type")
            
            if event_type == "content":
                # Streaming content
                print(event.get("content", ""), end="", flush=True)
                
            elif event_type == "tool_call":
                # Tool being called
                tool_name = event.get("tool_name", "unknown")
                args = event.get("arguments", {})
                print(f"\n🔧 Calling tool: {tool_name}")
                print(f"   Args: {args}")
                
            elif event_type == "tool_result":
                # Tool result (might be streaming)
                delta = event.get("delta", "")
                if delta:
                    print(delta, end="", flush=True)
                    
            elif event_type == "agent_done":
                # Agent finished
                print(f"\n\n✅ Agent done (reason: {event.get('reason', 'unknown')})")
                
            elif event_type == "error":
                # Error occurred
                print(f"\n❌ Error: {event.get('message', 'Unknown error')}")
        
        print("\n" + "=" * 50)
        
    finally:
        # Clean up
        await agent.cleanup()


async def run_with_thread_example():
    """
    Run an example conversation with thread persistence.
    """
    import uuid
    
    thread_id = f"example-{uuid.uuid4().hex[:8]}"
    agent = create_example_agent(thread_id=thread_id)
    
    try:
        await agent.initialize()
        
        print("\n" + "=" * 50)
        print(f"Kafka V1 Agent - Thread: {thread_id}")
        print("=" * 50 + "\n")
        
        # First message
        new_messages = [
            Message(role="user", content="Hello! What tools do you have?")
        ]
        
        print(f"User: {new_messages[0].content}\n")
        
        async for event in agent.run_with_thread(
            new_messages=new_messages,
            model="gpt-4o",
            save_to_thread=True
        ):
            event_type = event.get("type")
            if event_type == "content":
                print(event.get("content", ""), end="", flush=True)
            elif event_type == "agent_done":
                print(f"\n✅ Done")
        
        print("\n" + "-" * 30 + "\n")
        
        # Second message (will have history)
        new_messages = [
            Message(role="user", content="Thanks! Now tell me a joke.")
        ]
        
        print(f"User: {new_messages[0].content}\n")
        
        async for event in agent.run_with_thread(
            new_messages=new_messages,
            model="gpt-4o",
            save_to_thread=True
        ):
            event_type = event.get("type")
            if event_type == "content":
                print(event.get("content", ""), end="", flush=True)
            elif event_type == "agent_done":
                print(f"\n✅ Done")
        
        print("\n" + "=" * 50)
        
    finally:
        await agent.cleanup()


if __name__ == "__main__":
    # Run the stateless example
    asyncio.run(run_example())
    
    # Uncomment to run with thread:
    # asyncio.run(run_with_thread_example())
