"""
Counter Tool
============

Tool for counting slowly with streaming output.
"""

import asyncio

from src.tools import Tool


async def count_slowly(count: int = 10, delay: float = 1.0):
    """
    Count from 1 to count, yielding each number with a delay.
    This is a streaming tool handler (async generator).
    """
    for i in range(1, count + 1):
        await asyncio.sleep(delay)
        yield f"{i}... "
    yield "Done!"


count_tool = Tool(
    name="count_slowly",
    description="Count from 1 to a number slowly, with a delay between each number. Useful for demonstrating streaming tool results.",
    parameters={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "The number to count to. Defaults to 10.",
                "default": 10
            },
            "delay": {
                "type": "number",
                "description": "Seconds between each number. Defaults to 1.0.",
                "default": 1.0
            }
        },
        "required": []
    },
    handler=count_slowly
)
