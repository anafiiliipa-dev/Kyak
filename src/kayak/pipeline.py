"""
Data extraction pipeline: geocoding, weather, and hotel collection.

All network calls live here. Pure logic lives in scoring.py.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from urllib.parse import quote_plus

import pandas as pd
import requests

from kayak.config import (
    CITIES,
    DATA_DIR,
    ENRICHED_CITY_CSV,
    HEADERS,
    HOTELS_CSV,
    MAX_VALID_HOTELS_PER_CITY,
    MIN_VALID_HOTELS_PER_CITY,
    NOMINATIM_BASE_URL,
    OPEN_METEO_BASE_URL,
    OVERPASS_BASE_URL,
    REQUEST_TIMEOUT,
    SLEEP_SECONDS,
    TOP_HOTELS_CSV,
    logger,
)
from kayak.scoring import (
    build_city_id,
    build_city_level_dataset,
    build_hotel_level_dataset,
    build_osm_hotel_id,
    compute_distance_km,
    compute_weather_score,
    is_valid_hotel_row,
    normalize_city_name,
    safe_float,
)


# ── Session ───────────────────────────────────────────────────────────────────

def get_session() -> requests.Session:
    """Return a reusable HTTP session with default headers."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


# ── Geocoding ─────────────────────────────────────────────────────────────────

def geocode_city(session: requests.Session, city: str) -> dict:
    """
    Geocode one city via Nominatim.

    Returns a normalised city record with coordinates.

    Raises:
        ValueError: if Nominatim returns no results.
        requests.HTTPError: on non-2xx responses.
    """
    normalized = normalize_city_name(city)
    params = {"q": f"{normalized}, France", "format": "jsonv2", "limit": 1}

    response = session.get(NOMINATIM_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    results = response.json()
    if not results:
        raise ValueError(f"No geocoding result for: {city!r}")

    best = results[0]
    return {
        "city_id":      build_city_id(city),
        "city_name":    normalized,
        "country":      "France",
        "latitude":     float(best["lat"]),
        "longitude":    float(best["lon"]),
        "display_name": best.get("display_name"),
        "data_source":  "Nominatim",
        "collected_at": datetime.now(UTC).isoformat(),
    }


# ── Weather ───────────────────────────────────────────────────────────────────

def get_weather_for_city(session: requests.Session, city_row: dict) -> dict:
    """
    Fetch a 7-day weather forecast from Open-Meteo.

    NOTE: relative_humidity_2m is an HOURLY field in Open-Meteo — not daily.
    We fetch it separately via the hourly endpoint and aggregate to a daily mean.

    Returns a weather summary dict with a computed weather_score.

    Raises:
        ValueError: if Open-Meteo returns no daily data.
        requests.HTTPError: on non-2xx responses.
    """
    # ── Daily variables ───────────────────────────────────────────────────────
    daily_params = {
        "latitude":     city_row["latitude"],
        "longitude":    city_row["longitude"],
        "daily":        ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
        ]),
        "timezone":     "auto",
        "forecast_days": 7,
    }
    resp_daily = session.get(OPEN_METEO_BASE_URL, params=daily_params, timeout=REQUEST_TIMEOUT)
    resp_daily.raise_for_status()
    daily = resp_daily.json().get("daily", {})

    max_temps = daily.get("temperature_2m_max", [])
    min_temps = daily.get("temperature_2m_min", [])
    rain_sums = daily.get("precipitation_sum", [])
    pop_max   = daily.get("precipitation_probability_max", [])

    if not max_temps or not min_temps:
        raise ValueError(f"No daily weather data for {city_row['city_name']!r}")

    avg_temp   = sum((hi + lo) / 2 for hi, lo in zip(max_temps, min_temps)) / len(max_temps)
    total_rain = sum(v for v in rain_sums if v is not None)
    avg_pop    = (sum(v for v in pop_max if v is not None) / len(pop_max)) if pop_max else 0.0

    # ── Hourly humidity (aggregated to 7-day mean) ────────────────────────────
    hourly_params = {
        "latitude":     city_row["latitude"],
        "longitude":    city_row["longitude"],
        "hourly":       "relative_humidity_2m",
        "timezone":     "auto",
        "forecast_days": 7,
    }
    avg_humidity: float | None = None
    try:
        resp_hourly = session.get(OPEN_METEO_BASE_URL, params=hourly_params, timeout=REQUEST_TIMEOUT)
        resp_hourly.raise_for_status()
        hourly_vals = resp_hourly.json().get("hourly", {}).get("relative_humidity_2m", [])
        if hourly_vals:
            valid = [v for v in hourly_vals if v is not None]
            avg_humidity = round(sum(valid) / len(valid), 1) if valid else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Humidity fetch failed for %s: %s", city_row["city_name"], exc)

    weather_score = compute_weather_score(avg_temp, total_rain, avg_pop)

    return {
        "city_id":            city_row["city_id"],
        "city_name":          city_row["city_name"],
        "latitude":           city_row["latitude"],
        "longitude":          city_row["longitude"],
        "avg_temp_7d":        round(avg_temp, 2),
        "avg_humidity_7d":    avg_humidity,
        "total_rain_7d":      round(total_rain, 2),
        "avg_pop_7d":         round(avg_pop / 100, 4),
        "weather_score":      round(weather_score, 2),
        "weather_data_source": "Open-Meteo",
        "collected_at":       datetime.now(UTC).isoformat(),
    }


# ── Hotels (Overpass / OSM) ───────────────────────────────────────────────────

def _overpass_post(session: requests.Session, query: str) -> dict:
    """POST a raw Overpass QL query and return the parsed JSON payload."""
    response = session.post(
        OVERPASS_BASE_URL,
        data={"data": query},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_hotels_by_geocode(
    session: requests.Session,
    latitude: float,
    longitude: float,
    radius_km: int = 10,
) -> list[dict]:
    """
    Query OpenStreetMap via Overpass for hotels near (latitude, longitude).

    Returns a list of raw Overpass elements (nodes / ways / relations).
    """
    radius_m = radius_km * 1_000
    query = f"""
    [out:json][timeout:25];
    (
      node["tourism"="hotel"](around:{radius_m},{latitude},{longitude});
      way["tourism"="hotel"](around:{radius_m},{latitude},{longitude});
      relation["tourism"="hotel"](around:{radius_m},{latitude},{longitude});
    );
    out center tags;
    """
    payload = _overpass_post(session, query)
    return payload.get("elements", [])


def normalize_hotel_element(
    element: dict,
    city_row: dict,
) -> dict | None:
    """
    Convert one raw Overpass element into a clean hotel row.

    Returns None if the element lacks usable coordinates.
    """
    tags = element.get("tags", {})

    # Coordinates: nodes have lat/lon directly; ways/relations use center
    if "lat" in element and "lon" in element:
        lat = float(element["lat"])
        lon = float(element["lon"])
    elif "center" in element:
        lat = float(element["center"]["lat"])
        lon = float(element["center"]["lon"])
    else:
        return None

    hotel_id   = build_osm_hotel_id(element)
    hotel_name = tags.get("name") or tags.get("brand") or hotel_id

    stars_raw = tags.get("stars") or tags.get("tourism:stars")
    stars     = safe_float(stars_raw)

    distance_km = compute_distance_km(
        city_row["latitude"], city_row["longitude"], lat, lon
    )

    row = {
        "city_id":                  city_row["city_id"],
        "city_name":                city_row["city_name"],
        "hotel_id":                 hotel_id,
        "hotel_name":               hotel_name,
        "hotel_latitude":           lat,
        "hotel_longitude":          lon,
        "hotel_overall_rating":     stars,
        "distance_to_city_center_km": round(distance_km, 3),
        "osm_type":                 element.get("type"),
        "osm_id":                   element.get("id"),
        "collected_at":             datetime.now(UTC).isoformat(),
    }

    return row if is_valid_hotel_row(row) else None


# ── Collection orchestration ──────────────────────────────────────────────────

def collect_geocoded_cities(session: requests.Session) -> list[dict]:
    """Geocode all 35 project destinations, skipping failures."""
    results: list[dict] = []
    for city in CITIES:
        logger.info("Geocoding: %s", city)
        try:
            results.append(geocode_city(session, city))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Geocoding failed for %s: %s", city, exc)
        time.sleep(SLEEP_SECONDS)
    return results


def collect_weather_for_cities(
    session: requests.Session,
    city_rows: list[dict],
) -> list[dict]:
    """Fetch weather for all geocoded cities, skipping failures."""
    results: list[dict] = []
    for city_row in city_rows:
        logger.info("Weather: %s", city_row["city_name"])
        try:
            results.append(get_weather_for_city(session, city_row))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather failed for %s: %s", city_row["city_name"], exc)
        time.sleep(SLEEP_SECONDS)
    return results


def collect_hotels_for_all_cities(
    session: requests.Session,
    city_rows: list[dict],
    min_valid_hotels: int = MIN_VALID_HOTELS_PER_CITY,
    max_valid_hotels: int = MAX_VALID_HOTELS_PER_CITY,
) -> list[dict]:
    """
    Fetch and normalise hotel data for all geocoded cities.

    Cities with fewer than *min_valid_hotels* valid results are skipped
    with a warning.
    """
    all_hotel_rows: list[dict] = []

    for city_row in city_rows:
        logger.info("Hotels: %s", city_row["city_name"])
        try:
            elements = get_hotels_by_geocode(
                session,
                city_row["latitude"],
                city_row["longitude"],
            )
            rows = [
                r for el in elements
                if (r := normalize_hotel_element(el, city_row)) is not None
            ]

            if len(rows) < min_valid_hotels:
                logger.warning(
                    "Only %d valid hotels for %s (minimum %d) — skipping city.",
                    len(rows), city_row["city_name"], min_valid_hotels,
                )
                continue

            all_hotel_rows.extend(rows[:max_valid_hotels])

        except Exception as exc:  # noqa: BLE001
            logger.warning("Hotel collection failed for %s: %s", city_row["city_name"], exc)

        time.sleep(SLEEP_SECONDS)

    return all_hotel_rows


# ── Export helpers ────────────────────────────────────────────────────────────

def export_dataframe(df: pd.DataFrame, path: str | object) -> None:
    """Export *df* to CSV at *path* with UTF-8 encoding."""
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info("Exported %d rows → %s", len(df), path)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_pipeline(
    run_s3: bool = False,
    run_rds: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Execute the full Kayak pipeline.

    Steps:
        1. Geocode 35 French cities (Nominatim)
        2. Fetch 7-day weather per city (Open-Meteo)
        3. Fetch hotels per city (Overpass / OSM)
        4. Score, rank, and merge into clean DataFrames
        5. Export to local CSV files
        6. Optionally upload to S3 and/or load into RDS

    Args:
        run_s3:  Upload CSV files to AWS S3.
        run_rds: Load clean DataFrames into AWS RDS PostgreSQL.

    Returns:
        (city_df, hotel_df) — the two final DataFrames.
    """
    session = get_session()

    # ── Extract ───────────────────────────────────────────────────────────────
    logger.info("Step 1/3 — geocoding cities")
    geo_rows = collect_geocoded_cities(session)

    logger.info("Step 2/3 — fetching weather")
    weather_rows = collect_weather_for_cities(session, geo_rows)

    logger.info("Step 3/3 — fetching hotels")
    hotel_rows = collect_hotels_for_all_cities(session, geo_rows)

    # ── Transform ─────────────────────────────────────────────────────────────
    city_df  = build_city_level_dataset(geo_rows, weather_rows)
    hotel_df = build_hotel_level_dataset(hotel_rows)

    top_hotel_df = hotel_df[hotel_df["hotel_rank"] == 1].nlargest(20, "hotel_score")

    # ── Export (local) ────────────────────────────────────────────────────────
    export_dataframe(pd.DataFrame(geo_rows),     DATA_DIR / "cities_geocoded.csv")
    export_dataframe(pd.DataFrame(weather_rows), DATA_DIR / "cities_weather.csv")
    export_dataframe(pd.DataFrame(hotel_rows),   DATA_DIR / "hotels_osm.csv")
    export_dataframe(city_df,                    ENRICHED_CITY_CSV)
    export_dataframe(top_hotel_df,               TOP_HOTELS_CSV)

    # ── Load (optional) ───────────────────────────────────────────────────────
    if run_s3 or run_rds:
        from kayak.aws import run_aws_load  # lazy import — AWS deps optional
        run_aws_load(city_df, hotel_df, run_s3=run_s3, run_rds=run_rds)

    logger.info("Pipeline complete. %d cities | %d hotels", len(city_df), len(hotel_df))
    return city_df, hotel_df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Kayak pipeline.")
    parser.add_argument("--s3",  action="store_true", help="Upload results to S3")
    parser.add_argument("--rds", action="store_true", help="Load results into RDS")
    args = parser.parse_args()

    run_pipeline(run_s3=args.s3, run_rds=args.rds)
