"""
Unit tests for the Kayak pipeline.

All tests import directly from src/kayak — zero code duplication.
No network calls, no AWS, no filesystem writes required.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from kayak.scoring import (
    build_city_id,
    build_hotel_level_dataset,
    build_osm_hotel_id,
    compute_distance_km,
    compute_hotel_score,
    compute_weather_score,
    is_valid_hotel_row,
    normalize_city_name,
    safe_float,
)
from kayak.config import CITY_CORRECTIONS


# ── normalize_city_name ───────────────────────────────────────────────────────

class TestNormalizeCityName:
    def test_known_correction(self):
        assert normalize_city_name("St Malo") == "Saint-Malo"

    def test_unknown_city_unchanged(self):
        assert normalize_city_name("Paris") == "Paris"

    def test_all_corrections_applied(self):
        for raw, expected in CITY_CORRECTIONS.items():
            assert normalize_city_name(raw) == expected


# ── build_city_id ─────────────────────────────────────────────────────────────

class TestBuildCityId:
    def test_simple_city(self):
        assert build_city_id("Paris") == "city_paris"

    def test_city_with_spaces(self):
        assert build_city_id("La Rochelle") == "city_la_rochelle"

    def test_corrected_city(self):
        assert build_city_id("St Malo") == "city_saint_malo"

    def test_no_spaces_in_result(self):
        assert " " not in build_city_id("Aix en Provence")

    def test_stable_across_calls(self):
        assert build_city_id("Lyon") == build_city_id("Lyon")

    def test_starts_with_city_prefix(self):
        assert build_city_id("Dijon").startswith("city_")


# ── safe_float ────────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_valid_string(self):
        assert safe_float("3.5") == 3.5

    def test_integer_input(self):
        assert safe_float(4) == 4.0

    def test_none_returns_default(self):
        assert safe_float(None) is None
        assert safe_float(None, default=0.0) == 0.0

    def test_invalid_string_returns_default(self):
        assert safe_float("n/a") is None
        assert safe_float("n/a", default=-1.0) == -1.0

    def test_empty_string_returns_default(self):
        assert safe_float("") is None


# ── compute_distance_km ───────────────────────────────────────────────────────

class TestComputeDistanceKm:
    def test_same_point_is_zero(self):
        assert compute_distance_km(48.8566, 2.3522, 48.8566, 2.3522) == pytest.approx(0.0, abs=1e-6)

    def test_paris_to_lyon(self):
        # ~392 km
        d = compute_distance_km(48.8566, 2.3522, 45.7640, 4.8357)
        assert 380 < d < 410

    def test_symmetry(self):
        d1 = compute_distance_km(48.8566, 2.3522, 43.2965, 5.3698)
        d2 = compute_distance_km(43.2965, 5.3698, 48.8566, 2.3522)
        assert d1 == pytest.approx(d2, rel=1e-6)

    def test_positive_value(self):
        assert compute_distance_km(48.0, 2.0, 49.0, 3.0) > 0


# ── build_osm_hotel_id ────────────────────────────────────────────────────────

class TestBuildOsmHotelId:
    def test_node_type(self):
        assert build_osm_hotel_id({"type": "node", "id": 12345}) == "osm_node_12345"

    def test_relation_type(self):
        assert build_osm_hotel_id({"type": "relation", "id": 67890}) == "osm_relation_67890"

    def test_missing_type_uses_element(self):
        result = build_osm_hotel_id({"id": 999})
        assert result.startswith("osm_")
        assert "999" in result


# ── is_valid_hotel_row ────────────────────────────────────────────────────────

class TestIsValidHotelRow:
    def _valid(self) -> dict:
        return {
            "city_id":        "city_paris",
            "hotel_id":       "osm_node_1",
            "hotel_name":     "Hotel Test",
            "hotel_latitude":  48.8566,
            "hotel_longitude":  2.3522,
        }

    def test_valid_row(self):
        assert is_valid_hotel_row(self._valid()) is True

    def test_missing_city_id(self):
        r = self._valid(); r["city_id"] = None
        assert is_valid_hotel_row(r) is False

    def test_missing_hotel_id(self):
        r = self._valid(); del r["hotel_id"]
        assert is_valid_hotel_row(r) is False

    def test_none_latitude(self):
        r = self._valid(); r["hotel_latitude"] = None
        assert is_valid_hotel_row(r) is False

    def test_empty_hotel_name(self):
        r = self._valid(); r["hotel_name"] = ""
        assert is_valid_hotel_row(r) is False

    def test_empty_dict(self):
        assert is_valid_hotel_row({}) is False


# ── compute_weather_score ─────────────────────────────────────────────────────

class TestComputeWeatherScore:
    def test_increases_with_temperature(self):
        assert compute_weather_score(25, 0, 0) > compute_weather_score(10, 0, 0)

    def test_decreases_with_rain(self):
        assert compute_weather_score(20, 0, 0) > compute_weather_score(20, 10, 0)

    def test_decreases_with_pop(self):
        assert compute_weather_score(20, 0, 0) > compute_weather_score(20, 0, 50)


# ── compute_hotel_score ───────────────────────────────────────────────────────

class TestComputeHotelScore:
    def test_higher_rating_scores_higher(self):
        assert compute_hotel_score(5.0, 1.0) > compute_hotel_score(3.0, 1.0)

    def test_closer_scores_higher(self):
        assert compute_hotel_score(4.0, 0.5) > compute_hotel_score(4.0, 5.0)


# ── build_hotel_level_dataset ─────────────────────────────────────────────────

class TestBuildHotelLevelDataset:
    def _rows(self) -> list[dict]:
        return [
            {"city_id": "city_paris", "city_name": "Paris", "hotel_id": "osm_1",
             "hotel_name": "A Hotel", "hotel_latitude": 48.85, "hotel_longitude": 2.35,
             "hotel_overall_rating": 4.0, "distance_to_city_center_km": 0.5},
            {"city_id": "city_paris", "city_name": "Paris", "hotel_id": "osm_2",
             "hotel_name": "B Hotel", "hotel_latitude": 48.86, "hotel_longitude": 2.36,
             "hotel_overall_rating": 3.0, "distance_to_city_center_km": 1.0},
            {"city_id": "city_lyon",  "city_name": "Lyon",  "hotel_id": "osm_3",
             "hotel_name": "C Hotel", "hotel_latitude": 45.76, "hotel_longitude": 4.83,
             "hotel_overall_rating": 5.0, "distance_to_city_center_km": 0.2},
        ]

    def test_returns_dataframe(self):
        assert isinstance(build_hotel_level_dataset(self._rows()), pd.DataFrame)

    def test_rank_starts_at_1_per_city(self):
        df = build_hotel_level_dataset(self._rows())
        for _, group in df.groupby("city_name"):
            assert group["hotel_rank"].min() == 1

    def test_rank_is_sequential(self):
        df = build_hotel_level_dataset(self._rows())
        for _, group in df.groupby("city_name"):
            ranks = sorted(group["hotel_rank"].tolist())
            assert ranks == list(range(1, len(ranks) + 1))

    def test_better_hotel_ranks_first(self):
        df = build_hotel_level_dataset(self._rows())
        paris = df[df["city_name"] == "Paris"].reset_index(drop=True)
        # A Hotel: score = 4*10 - 0.5*2 = 39.0 > B Hotel: 3*10 - 1.0*2 = 28.0
        assert paris.loc[0, "hotel_name"] == "A Hotel"

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="No hotel data available"):
            build_hotel_level_dataset([])

    def test_missing_rating_filled(self):
        rows = self._rows()
        rows[0]["hotel_overall_rating"] = None
        df = build_hotel_level_dataset(rows)
        assert df["rating_for_score"].notna().all()

    def test_score_column_present(self):
        df = build_hotel_level_dataset(self._rows())
        assert "hotel_score" in df.columns
