"""A real, working MCP server for worldwide weather — Open-Meteo (free, no API
key, global coverage). Runs over stdio, spawned as a subprocess by Agent
Forge's mcp_tool (StdioConnectionParams), exactly like a real external MCP
server would be, just running locally instead of over HTTP.

Run standalone for a smoke test:
    python mcp_servers/weather_server.py
(it will just sit waiting for stdio input — Ctrl+C to stop)
"""

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from _http_retry import get_with_retry

mcp = FastMCP("weather")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes (used by Open-Meteo) -> plain-English text.
_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _describe(code: int) -> str:
    return _WEATHER_CODES.get(code, f"Unknown conditions (code {code})")


async def _geocode_query(client: httpx.AsyncClient, name: str) -> dict[str, Any] | None:
    try:
        response = await get_with_retry(
            client,
            GEOCODING_URL,
            params={"name": name, "count": 1, "language": "en", "format": "json"},
            timeout=30.0,
        )
        response.raise_for_status()
        results = response.json().get("results")
    except Exception:
        return None
    return results[0] if results else None


async def _geocode(location: str) -> dict[str, Any] | None:
    """Resolves a place name to coordinates.

    Open-Meteo's geocoder matches against a single gazetteer entry per name, so
    a compound name like "Pimpri Chinchwad" (a twin city usually indexed under
    just "Pimpri") can miss on the first try. Fall back to shorter prefixes of
    the name (splitting on the first comma, then on whitespace) before giving up.
    """
    async with httpx.AsyncClient() as client:
        candidates = [location, location.split(",")[0].strip()]
        words = candidates[-1].split()
        if len(words) > 1:
            candidates.append(words[0])

        for candidate in candidates:
            place = await _geocode_query(client, candidate)
            if place is not None:
                return place
    return None


async def _fetch_forecast(latitude: float, longitude: float, params: dict[str, Any]) -> dict[str, Any] | None:
    async with httpx.AsyncClient() as client:
        try:
            response = await get_with_retry(
                client,
                FORECAST_URL,
                params={"latitude": latitude, "longitude": longitude, "timezone": "auto", **params},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


def _place_label(place: dict[str, Any]) -> str:
    parts = [place.get("name")]
    if place.get("admin1"):
        parts.append(place["admin1"])
    if place.get("country"):
        parts.append(place["country"])
    return ", ".join(p for p in parts if p)


@mcp.tool()
async def get_forecast(location: str) -> str:
    """Get a multi-day weather forecast for any place in the world.

    Args:
        location: A place name, e.g. "Pimpri Chinchwad", "Paris, France", "Tokyo".
    """
    place = await _geocode(location)
    if place is None:
        return f"Couldn't find a location matching '{location}'. Try a more specific name (add a country)."

    data = await _fetch_forecast(
        place["latitude"],
        place["longitude"],
        {
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 5,
        },
    )
    if data is None or "daily" not in data:
        return f"Unable to fetch forecast data for {_place_label(place)}."

    daily = data["daily"]
    lines = [f"Forecast for {_place_label(place)}:"]
    for i, date in enumerate(daily["time"]):
        lines.append(
            f"{date}: {_describe(daily['weathercode'][i])}, "
            f"high {daily['temperature_2m_max'][i]}°C / low {daily['temperature_2m_min'][i]}°C, "
            f"{daily['precipitation_probability_max'][i]}% chance of precipitation"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_current_weather(location: str) -> str:
    """Get current weather conditions for any place in the world.

    Args:
        location: A place name, e.g. "Pimpri Chinchwad", "Paris, France", "Tokyo".
    """
    place = await _geocode(location)
    if place is None:
        return f"Couldn't find a location matching '{location}'. Try a more specific name (add a country)."

    data = await _fetch_forecast(place["latitude"], place["longitude"], {"current_weather": True})
    if data is None or "current_weather" not in data:
        return f"Unable to fetch current conditions for {_place_label(place)}."

    current = data["current_weather"]
    return (
        f"Current weather in {_place_label(place)}:\n"
        f"Temperature: {current['temperature']}°C\n"
        f"Wind speed: {current['windspeed']} km/h\n"
        f"Conditions: {_describe(current['weathercode'])}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
