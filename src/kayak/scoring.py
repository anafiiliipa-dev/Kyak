"""
Pure scoring and ranking functions.

All functions here are side-effect-free and fully unit-testable
without any network calls or filesystem access.
"""
from __future__ import annotations

import math

import pandas as pd

from kayak.config import (
    HOTEL_SCORE_DISTANCE_WEIGHT,
    HOTEL_SCORE_RATING_WEIGHT,
    WEATHER_SCORE_POP_WEIGHT,
    WEATHER_SCORE_RAIN_WEIGHT,
    WEATHER_SCORE_TEMP_WEIGHT,
    CITY_CORRECTIONS,
)


# ── City helpers ──────────────────────────────────────────────────────────────

def normalize_city_name(city: str) -> str:
    """Return the corrected canonical name for a city."""
    return CITY_CORRECTIONS.get(city, city)


def build_city_id(city: str) -> str:
    """
    Create a stable, URL-safe identifier for a city.

    Examples:
        >>> build_city_id("Paris")
        'city_paris'
        >>> build_city_id("Aix en Provence")
        'city_aix_en_provence'
    """
    slug = normalize_city_name(city).lower()
    slug = slug.replace("'", "").replace(" ", "_").replace("-", "_")
    slug = "".join(ch for ch in slug if ch.isalnum() or ch == "_")
    return f"city_{slug}"


# ── Numeric helpers ───────────────────────────────────────────────────────────

def safe_float(value: object, default: float | None = None) -> float | None:
    """Safely cast *value* to float, returning *default* on failure."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def compute_distance_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """
    Great-circle distance between two points (Haversine formula).

    Returns distance in kilometres.
    """
    radius_km = 6_371.0
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Validation ────────────────────────────────────────────────────────────────

def is_valid_hotel_row(row: dict) -> bool:
    """Return True only if *row* has all required hotel fields."""
    return bool(
        row
        and row.get("city_id")
        and row.get("hotel_id")
        and row.get("hotel_name")
        and row.get("hotel_latitude") is not None
        and row.get("hotel_longitude") is not None
    )


# ── OSM helpers ───────────────────────────────────────────────────────────────

def build_osm_hotel_id(hotel_item: dict) -> str:
    """Build a stable ID string from an Overpass API element."""
    return f"osm_{hotel_item.get('type', 'element')}_{hotel_item.get('id')}"


# ── Scoring ───────────────────────────────────────────────────────────────────

def compute_weather_score(
    avg_temp: float,
    total_rain: float,
    avg_pop: float,
) -> float:
    """
    Score a destination's weather for the next 7 days.

    Higher is better.

    Args:
        avg_temp:   Average daily temperature (°C).
        total_rain: Total precipitation sum over 7 days (mm).
        avg_pop:    Average precipitation probability (0–100).
    """
    return (
        WEATHER_SCORE_TEMP_WEIGHT * avg_temp
        - WEATHER_SCORE_RAIN_WEIGHT * total_rain
        - WEATHER_SCORE_POP_WEIGHT  * avg_pop
    )


def compute_hotel_score(rating: float, distance_km: float) -> float:
    """
    Score a hotel based on rating and proximity to city centre.

    Higher is better.

    Args:
        rating:      Overall rating (e.g. 0–5 stars).
        distance_km: Distance from city centre in kilometres.
    """
    return (
        HOTEL_SCORE_RATING_WEIGHT   * rating
        - HOTEL_SCORE_DISTANCE_WEIGHT * distance_km
    )


# ── Dataset builders ──────────────────────────────────────────────────────────

def build_hotel_level_dataset(hotel_rows: list[dict]) -> pd.DataFrame:
    """
    Build a clean, scored, and ranked hotel DataFrame.

    Raises:
        ValueError: if *hotel_rows* is empty.
    """
    if not hotel_rows:
        raise ValueError("No hotel data available.")

    df = pd.DataFrame(hotel_rows)
    df["hotel_overall_rating"]       = pd.to_numeric(df["hotel_overall_rating"],       errors="coerce")
    df["distance_to_city_center_km"] = pd.to_numeric(df["distance_to_city_center_km"], errors="coerce")

    rating_fallback   = df["hotel_overall_rating"].median()
    distance_fallback = df["distance_to_city_center_km"].median()

    if pd.isna(rating_fallback):
        rating_fallback = 0.0
    if pd.isna(distance_fallback):
        distance_fallback = 999.0

    df["rating_for_score"]   = df["hotel_overall_rating"].fillna(rating_fallback)
    df["distance_for_score"] = df["distance_to_city_center_km"].fillna(distance_fallback)

    df["hotel_score"] = df.apply(
        lambda r: compute_hotel_score(r["rating_for_score"], r["distance_for_score"]),
        axis=1,
    )

    df = df.sort_values(
        ["city_name", "hotel_score"], ascending=[True, False]
    ).reset_index(drop=True)

    df["hotel_rank"] = df.groupby("city_name").cumcount() + 1
    return df


def build_city_level_dataset(
    geo_rows: list[dict],
    weather_rows: list[dict],
) -> pd.DataFrame:
    """
    Merge geocoding and weather data into a single ranked city DataFrame.

    Raises:
        ValueError: if either input list is empty.
    """
    if not geo_rows or not weather_rows:
        raise ValueError("Geocoding and weather data are both required.")

    geo_df     = pd.DataFrame(geo_rows)
    weather_df = pd.DataFrame(weather_rows)

    merged = geo_df.merge(
        weather_df[["city_id", "avg_temp_7d", "avg_humidity_7d",
                    "total_rain_7d", "avg_pop_7d", "weather_score"]],
        on="city_id",
        how="left",
    )

    merged = merged.sort_values("weather_score", ascending=False).reset_index(drop=True)
    merged["destination_rank"] = merged.index + 1
    return merged
