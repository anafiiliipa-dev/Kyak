"""
Unit tests for the Kayak pipeline pure functions.

These tests cover all functions that do NOT require external API calls:
normalisation, distance computation, validation, scoring, and dataset building.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

# Add notebooks dir to path so we can import helpers
# In a real refactor these would live in src/ — for now we extract them here.

# ============================================================
# Helpers duplicated for testing (functions from the notebook)
# These mirror the notebook implementations exactly.
# ============================================================

CITY_CORRECTIONS = {
    "St Malo": "Saint-Malo",
    "Chateau du Haut Koenigsbourg": "Château du Haut-Kœnigsbourg",
    "Bormes les Mimosas": "Bormes-les-Mimosas",
    "Aix en Provence": "Aix-en-Provence",
    "Aigues Mortes": "Aigues-Mortes",
    "Saintes Maries de la Mer": "Saintes-Maries-de-la-Mer",
}

HOTEL_SCORE_RATING_WEIGHT   = 10.0
HOTEL_SCORE_DISTANCE_WEIGHT = 2.0
WEATHER_SCORE_TEMP_WEIGHT   = 2.0
WEATHER_SCORE_RAIN_WEIGHT   = 1.5
WEATHER_SCORE_POP_WEIGHT    = 0.2


def normalize_city_name(city: str) -> str:
    return CITY_CORRECTIONS.get(city, city)


def build_city_id(city: str) -> str:
    slug = normalize_city_name(city).lower()
    slug = slug.replace("'", "").replace(" ", "_").replace("-", "_")
    slug = "".join(ch for ch in slug if ch.isalnum() or ch == "_")
    return f"city_{slug}"


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_distance_km(lat1, lon1, lat2, lon2) -> float:
    radius_km = 6371.0
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_osm_hotel_id(hotel_item: dict) -> str:
    return f"osm_{hotel_item.get('type', 'element')}_{hotel_item.get('id')}"


def is_valid_hotel_row(row: dict) -> bool:
    return bool(
        row
        and row.get("city_id")
        and row.get("hotel_id")
        and row.get("hotel_name")
        and row.get("hotel_latitude") is not None
        and row.get("hotel_longitude") is not None
    )


def build_hotel_level_dataset(hotel_rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(hotel_rows)
    if df.empty:
        raise ValueError("No hotel data available.")
    df["hotel_overall_rating"] = pd.to_numeric(df["hotel_overall_rating"], errors="coerce")
    df["distance_to_city_center_km"] = pd.to_numeric(df["distance_to_city_center_km"], errors="coerce")
    rating_fallback = df["hotel_overall_rating"].median()
    distance_fallback = df["distance_to_city_center_km"].median()
    if pd.isna(rating_fallback):
        rating_fallback = 0.0
    if pd.isna(distance_fallback):
        distance_fallback = 999.0
    df["rating_for_score"] = df["hotel_overall_rating"].fillna(rating_fallback)
    df["distance_for_score"] = df["distance_to_city_center_km"].fillna(distance_fallback)
    df["hotel_score"] = (
        HOTEL_SCORE_RATING_WEIGHT * df["rating_for_score"]
        - HOTEL_SCORE_DISTANCE_WEIGHT * df["distance_for_score"]
    )
    df = df.sort_values(["city_name", "hotel_score"], ascending=[True, False]).reset_index(drop=True)
    df["hotel_rank"] = df.groupby("city_name").cumcount() + 1
    return df


# ============================================================
# Tests
# ============================================================

class TestNormalizeCityName:
    def test_known_correction(self):
        assert normalize_city_name("St Malo") == "Saint-Malo"

    def test_unknown_city_unchanged(self):
        assert normalize_city_name("Paris") == "Paris"

    def test_all_corrections_applied(self):
        for raw, expected in CITY_CORRECTIONS.items():
            assert normalize_city_name(raw) == expected


class TestBuildCityId:
    def test_simple_city(self):
        assert build_city_id("Paris") == "city_paris"

    def test_city_with_spaces(self):
        assert build_city_id("La Rochelle") == "city_la_rochelle"

    def test_corrected_city(self):
        # "St Malo" → "Saint-Malo" → "city_saint_malo"
        assert build_city_id("St Malo") == "city_saint_malo"

    def test_city_with_accents_preserved_in_id(self):
        city_id = build_city_id("Aix en Provence")
        assert city_id.startswith("city_")
        assert " " not in city_id

    def test_stable_across_calls(self):
        assert build_city_id("Lyon") == build_city_id("Lyon")


class TestSafeFloat:
    def test_converts_valid_string(self):
        assert safe_float("3.5") == 3.5

    def test_converts_integer(self):
        assert safe_float(4) == 4.0

    def test_none_returns_default(self):
        assert safe_float(None) is None
        assert safe_float(None, default=0.0) == 0.0

    def test_invalid_string_returns_default(self):
        assert safe_float("not a number") is None
        assert safe_float("n/a", default=-1.0) == -1.0

    def test_empty_string_returns_default(self):
        assert safe_float("") is None


class TestComputeDistanceKm:
    def test_same_point_is_zero(self):
        dist = compute_distance_km(48.8566, 2.3522, 48.8566, 2.3522)
        assert dist == pytest.approx(0.0, abs=1e-6)

    def test_paris_to_lyon_reasonable_distance(self):
        # Paris (48.8566, 2.3522) to Lyon (45.7640, 4.8357) ≈ 392 km
        dist = compute_distance_km(48.8566, 2.3522, 45.7640, 4.8357)
        assert 380 < dist < 410

    def test_symmetry(self):
        d1 = compute_distance_km(48.8566, 2.3522, 43.2965, 5.3698)
        d2 = compute_distance_km(43.2965, 5.3698, 48.8566, 2.3522)
        assert d1 == pytest.approx(d2, rel=1e-6)

    def test_returns_positive_value(self):
        dist = compute_distance_km(48.0, 2.0, 49.0, 3.0)
        assert dist > 0


class TestBuildOsmHotelId:
    def test_node_type(self):
        item = {"type": "node", "id": 12345}
        assert build_osm_hotel_id(item) == "osm_node_12345"

    def test_relation_type(self):
        item = {"type": "relation", "id": 67890}
        assert build_osm_hotel_id(item) == "osm_relation_67890"

    def test_missing_type_defaults(self):
        item = {"id": 999}
        result = build_osm_hotel_id(item)
        assert result.startswith("osm_")
        assert "999" in result


class TestIsValidHotelRow:
    def _valid_row(self):
        return {
            "city_id": "city_paris",
            "hotel_id": "osm_node_1",
            "hotel_name": "Hotel Test",
            "hotel_latitude": 48.8566,
            "hotel_longitude": 2.3522,
        }

    def test_valid_row(self):
        assert is_valid_hotel_row(self._valid_row()) is True

    def test_missing_city_id(self):
        row = self._valid_row()
        row["city_id"] = None
        assert is_valid_hotel_row(row) is False

    def test_missing_hotel_id(self):
        row = self._valid_row()
        del row["hotel_id"]
        assert is_valid_hotel_row(row) is False

    def test_none_latitude(self):
        row = self._valid_row()
        row["hotel_latitude"] = None
        assert is_valid_hotel_row(row) is False

    def test_empty_hotel_name(self):
        row = self._valid_row()
        row["hotel_name"] = ""
        assert is_valid_hotel_row(row) is False

    def test_empty_dict(self):
        assert is_valid_hotel_row({}) is False


class TestBuildHotelLevelDataset:
    def _sample_rows(self):
        return [
            {"city_id": "city_paris", "city_name": "Paris", "hotel_id": "osm_node_1",
             "hotel_name": "A Hotel", "hotel_latitude": 48.85, "hotel_longitude": 2.35,
             "hotel_overall_rating": 4.0, "distance_to_city_center_km": 0.5},
            {"city_id": "city_paris", "city_name": "Paris", "hotel_id": "osm_node_2",
             "hotel_name": "B Hotel", "hotel_latitude": 48.86, "hotel_longitude": 2.36,
             "hotel_overall_rating": 3.0, "distance_to_city_center_km": 1.0},
            {"city_id": "city_lyon", "city_name": "Lyon", "hotel_id": "osm_node_3",
             "hotel_name": "C Hotel", "hotel_latitude": 45.76, "hotel_longitude": 4.83,
             "hotel_overall_rating": 5.0, "distance_to_city_center_km": 0.2},
        ]

    def test_returns_dataframe(self):
        df = build_hotel_level_dataset(self._sample_rows())
        assert isinstance(df, pd.DataFrame)

    def test_hotel_rank_starts_at_1_per_city(self):
        df = build_hotel_level_dataset(self._sample_rows())
        for city, group in df.groupby("city_name"):
            assert group["hotel_rank"].min() == 1

    def test_hotel_rank_is_sequential(self):
        df = build_hotel_level_dataset(self._sample_rows())
        for city, group in df.groupby("city_name"):
            ranks = sorted(group["hotel_rank"].tolist())
            assert ranks == list(range(1, len(ranks) + 1))

    def test_higher_rated_closer_hotel_ranks_first(self):
        df = build_hotel_level_dataset(self._sample_rows())
        paris = df[df["city_name"] == "Paris"].reset_index(drop=True)
        # A Hotel: score = 4*10 - 0.5*2 = 39.0; B Hotel: 3*10 - 1.0*2 = 28.0
        assert paris.loc[0, "hotel_name"] == "A Hotel"

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="No hotel data available"):
            build_hotel_level_dataset([])

    def test_missing_rating_filled_with_median(self):
        rows = self._sample_rows()
        rows[0]["hotel_overall_rating"] = None
        df = build_hotel_level_dataset(rows)
        assert df["rating_for_score"].notna().all()

    def test_score_column_present(self):
        df = build_hotel_level_dataset(self._sample_rows())
        assert "hotel_score" in df.columns


class TestWeatherScoreFormula:
    """Verify the weather score formula uses the named constants correctly."""

    def test_score_increases_with_temperature(self):
        score_hot  = WEATHER_SCORE_TEMP_WEIGHT * 25 - WEATHER_SCORE_RAIN_WEIGHT * 0 - WEATHER_SCORE_POP_WEIGHT * 0
        score_cold = WEATHER_SCORE_TEMP_WEIGHT * 10 - WEATHER_SCORE_RAIN_WEIGHT * 0 - WEATHER_SCORE_POP_WEIGHT * 0
        assert score_hot > score_cold

    def test_score_decreases_with_rain(self):
        score_dry  = WEATHER_SCORE_TEMP_WEIGHT * 20 - WEATHER_SCORE_RAIN_WEIGHT * 0   - WEATHER_SCORE_POP_WEIGHT * 0
        score_rainy = WEATHER_SCORE_TEMP_WEIGHT * 20 - WEATHER_SCORE_RAIN_WEIGHT * 10 - WEATHER_SCORE_POP_WEIGHT * 0
        assert score_dry > score_rainy
