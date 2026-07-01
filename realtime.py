# realtime.py — Real-time tools for J.A.R.V.I.S.
# Time & date: Python datetime (no API)
# Weather:     wttr.in JSON API (free, no key, city-based)
import logging
from datetime import datetime

import requests

log = logging.getLogger(__name__)

_WEATHER_TIMEOUT = 8  # seconds

# wttr.in weather code → human description (subset of WMO codes)
_WMO_DESC = {
    113: "clear skies",
    116: "partly cloudy",
    119: "cloudy",
    122: "overcast",
    143: "misty",
    176: "patchy rain nearby",
    179: "patchy snow nearby",
    182: "patchy sleet nearby",
    185: "patchy freezing drizzle nearby",
    200: "thundery outbreaks nearby",
    227: "blowing snow",
    230: "blizzard",
    248: "fog",
    260: "freezing fog",
    263: "light drizzle",
    266: "light drizzle",
    281: "freezing drizzle",
    284: "heavy freezing drizzle",
    293: "light rain",
    296: "light rain",
    299: "moderate rain",
    302: "moderate rain",
    305: "heavy rain",
    308: "heavy rain",
    311: "light freezing rain",
    314: "moderate or heavy freezing rain",
    317: "light sleet",
    320: "moderate or heavy sleet",
    323: "light snow",
    326: "light snow",
    329: "moderate snow",
    332: "moderate snow",
    335: "heavy snow",
    338: "heavy snow",
    350: "ice pellets",
    353: "light rain showers",
    356: "moderate or heavy rain showers",
    359: "torrential rain showers",
    362: "light sleet showers",
    365: "moderate or heavy sleet showers",
    368: "light snow showers",
    371: "moderate or heavy snow showers",
    374: "light showers of ice pellets",
    377: "moderate or heavy showers of ice pellets",
    386: "patchy light rain with thunder",
    389: "moderate or heavy rain with thunder",
    392: "patchy light snow with thunder",
    395: "heavy snow with thunder",
}


# ── Time ─────────────────────────────────────────────────────────────────────

def get_time() -> str:
    """Return current local time as a spoken string."""
    now = datetime.now()
    return now.strftime("%I:%M %p").lstrip("0")  # e.g. "3:47 PM"


def get_date() -> str:
    """Return current local date as a spoken string."""
    now = datetime.now()
    # e.g. "Tuesday, July 1st, 2025"
    day   = now.strftime("%A")
    month = now.strftime("%B")
    year  = now.strftime("%Y")
    d     = now.day
    suffix = (
        "th" if 11 <= d <= 13 else
        {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    )
    return f"{day}, {month} {d}{suffix}, {year}"


# ── Weather ───────────────────────────────────────────────────────────────────

def get_weather(city: str) -> dict:
    """
    Fetch current weather for *city* from wttr.in.

    Returns a dict with keys:
        city, country, temp_c, feels_like_c, description, humidity, wind_kmph
    Raises RuntimeError on network/parse failure.
    """
    city = city.strip()
    if not city:
        raise ValueError("No city provided.")

    url = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
    try:
        r = requests.get(
            url,
            timeout=_WEATHER_TIMEOUT,
            headers={"User-Agent": "curl/7.79.1"},   # wttr.in blocks some UA strings
        )
        r.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError("Weather service timed out.")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Weather request failed: {exc}")

    try:
        data    = r.json()
        current = data["current_condition"][0]
        area    = data["nearest_area"][0]

        city_name = area["areaName"][0]["value"]
        country   = area["country"][0]["value"]
        temp_c    = int(current["temp_C"])
        feels_c   = int(current["FeelsLikeC"])
        humidity  = int(current["humidity"])
        wind_kmph = int(current["windspeedKmph"])
        wmo_code  = int(current.get("weatherCode", 0))
        desc      = _WMO_DESC.get(wmo_code, current["weatherDesc"][0]["value"])

        return {
            "city":         city_name,
            "country":      country,
            "temp_c":       temp_c,
            "feels_like_c": feels_c,
            "description":  desc,
            "humidity":     humidity,
            "wind_kmph":    wind_kmph,
        }
    except (KeyError, IndexError, ValueError) as exc:
        log.error("[realtime] Weather parse error: %s — raw: %.200s", exc, r.text)
        raise RuntimeError(f"Couldn't parse weather data: {exc}")


def format_weather(w: dict) -> str:
    """Turn a weather dict into a natural spoken sentence."""
    feels_note = ""
    diff = w["feels_like_c"] - w["temp_c"]
    if diff <= -3:
        feels_note = f", though it feels closer to {w['feels_like_c']}°C"
    elif diff >= 3:
        feels_note = f", though it feels warmer at {w['feels_like_c']}°C"

    return (
        f"{w['city']}, {w['country']}: {w['description']}, "
        f"{w['temp_c']}°C{feels_note}. "
        f"Humidity {w['humidity']}%, wind {w['wind_kmph']} km/h."
    )
