"""
Example Tool Handlers
=====================

Example tools for demonstrating Kafka agent capabilities.
"""

import asyncio
import httpx

from src.tools import Tool


async def get_weather(location: str, units: str = "celsius") -> str:
    """
    Get current weather for a location using Open-Meteo API.
    
    Args:
        location: City name or location (e.g., "New York", "London, UK")
        units: Temperature units - "celsius" or "fahrenheit"
    
    Returns:
        Weather information as a formatted string
    """
    async with httpx.AsyncClient() as client:
        # Step 1: Geocode the location to get coordinates
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocode_response = await client.get(
            geocode_url,
            params={"name": location, "count": 1, "language": "en", "format": "json"}
        )
        geocode_data = geocode_response.json()
        
        if not geocode_data.get("results"):
            return f"Could not find location: {location}"
        
        result = geocode_data["results"][0]
        lat = result["latitude"]
        lon = result["longitude"]
        location_name = result.get("name", location)
        country = result.get("country", "")
        
        # Step 2: Get weather data
        weather_url = "https://api.open-meteo.com/v1/forecast"
        temp_unit = "fahrenheit" if units.lower() == "fahrenheit" else "celsius"
        
        weather_response = await client.get(
            weather_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "temperature_unit": temp_unit,
                "wind_speed_unit": "mph",
                "timezone": "auto"
            }
        )
        weather_data = weather_response.json()
        
        current = weather_data.get("current", {})
        
        # Weather code to description mapping
        weather_codes = {
            0: "Clear sky",
            1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Foggy", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
        }
        
        weather_code = current.get("weather_code", 0)
        condition = weather_codes.get(weather_code, "Unknown")
        temp = current.get("temperature_2m", "N/A")
        feels_like = current.get("apparent_temperature", "N/A")
        humidity = current.get("relative_humidity_2m", "N/A")
        wind = current.get("wind_speed_10m", "N/A")
        precipitation = current.get("precipitation", 0)
        
        unit_symbol = "°F" if temp_unit == "fahrenheit" else "°C"
        
        return (
            f"Weather in {location_name}, {country}:\n"
            f"• Condition: {condition}\n"
            f"• Temperature: {temp}{unit_symbol} (feels like {feels_like}{unit_symbol})\n"
            f"• Humidity: {humidity}%\n"
            f"• Wind: {wind} mph\n"
            f"• Precipitation: {precipitation} mm"
        )


async def count_slowly(count: int = 10, delay: float = 1.0):
    """
    Count from 1 to count, yielding each number with a delay.
    This is a streaming tool handler (async generator).
    """
    for i in range(1, count + 1):
        await asyncio.sleep(delay)
        yield f"{i}... "
    yield "Done!"


# Pre-configured Tool instances
get_weather_tool = Tool(
    name="get_weather",
    description="Get the current weather for a location. Returns temperature, conditions, humidity, and wind speed.",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The city and optionally country, e.g. 'San Francisco' or 'Paris, France'"
            },
            "units": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "Temperature units. Defaults to celsius."
            }
        },
        "required": ["location"]
    },
    handler=get_weather
)


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


# Default MCP servers
DEFAULT_MCP_SERVERS = [
    {
        "name": "sequential-thinking",
        "url": "https://remote.mcpservers.org/sequentialthinking/mcp"
    },
    {
        "name": "fetch",
        "url": "https://remote.mcpservers.org/fetch/mcp"
    }
]
