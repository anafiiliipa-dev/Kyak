"""
Centralised configuration for the Kayak pipeline.

All tuneable parameters live here. Nothing else imports constants
from the notebook or from each other — only from this module.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

CITY_GEO_CSV      = DATA_DIR / "cities_geocoded.csv"
CITY_WEATHER_CSV  = DATA_DIR / "cities_weather.csv"
HOTELS_CSV        = DATA_DIR / "hotels_osm.csv"
ENRICHED_CITY_CSV = DATA_DIR / "cities_enriched.csv"
TOP_HOTELS_CSV    = DATA_DIR / "top_hotels.csv"

# ── HTTP ──────────────────────────────────────────────────────────────────────
USER_AGENT      = "kayak-destination-project/2.0 (student-project)"
REQUEST_TIMEOUT = 30
SLEEP_SECONDS   = 1.1   # Nominatim ToS: max 1 req/s

NOMINATIM_BASE_URL  = "https://nominatim.openstreetmap.org/search"
OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_BASE_URL   = "https://overpass-api.de/api/interpreter"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept":     "application/json",
}

# ── Hotel collection ──────────────────────────────────────────────────────────
MIN_VALID_HOTELS_PER_CITY = 5
MAX_VALID_HOTELS_PER_CITY = 10
HOTEL_SEARCH_RADIUS_KM    = 10

# ── Scoring weights ───────────────────────────────────────────────────────────
# weather_score = TEMP_W * avg_temp - RAIN_W * total_rain - POP_W * avg_pop
WEATHER_SCORE_TEMP_WEIGHT: float = 2.0
WEATHER_SCORE_RAIN_WEIGHT: float = 1.5
WEATHER_SCORE_POP_WEIGHT:  float = 0.2

# hotel_score = RATING_W * stars - DISTANCE_W * km_to_centre
HOTEL_SCORE_RATING_WEIGHT:   float = 10.0
HOTEL_SCORE_DISTANCE_WEIGHT: float = 2.0

# ── AWS (loaded from .env) ────────────────────────────────────────────────────
AWS_REGION     = os.getenv("AWS_REGION", "eu-west-3")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_RAW_PREFIX  = "kayak/raw"
S3_CLEAN_PREFIX = "kayak/clean"

RDS_HOST    = os.getenv("RDS_HOST")
RDS_PORT    = os.getenv("RDS_PORT", "5432")
RDS_DB_NAME = os.getenv("RDS_DB_NAME")
RDS_USER    = os.getenv("RDS_USER")
RDS_PASSWORD = os.getenv("RDS_PASSWORD")
RDS_SCHEMA  = os.getenv("RDS_SCHEMA", "public")

# ── Cities ────────────────────────────────────────────────────────────────────
CITIES: list[str] = [
    "Mont Saint Michel", "St Malo", "Bayeux", "Le Havre", "Rouen",
    "Paris", "Amiens", "Lille", "Strasbourg",
    "Chateau du Haut Koenigsbourg", "Colmar", "Eguisheim", "Besancon",
    "Dijon", "Annecy", "Grenoble", "Lyon", "Gorges du Verdon",
    "Bormes les Mimosas", "Cassis", "Marseille", "Aix en Provence",
    "Avignon", "Uzes", "Nimes", "Aigues Mortes",
    "Saintes Maries de la Mer", "Collioure", "Carcassonne", "Ariege",
    "Toulouse", "Montauban", "Biarritz", "Bayonne", "La Rochelle",
]

CITY_CORRECTIONS: dict[str, str] = {
    "St Malo":                      "Saint-Malo",
    "Chateau du Haut Koenigsbourg": "Château du Haut-Kœnigsbourg",
    "Bormes les Mimosas":           "Bormes-les-Mimosas",
    "Aix en Provence":              "Aix-en-Provence",
    "Aigues Mortes":                "Aigues-Mortes",
    "Saintes Maries de la Mer":     "Saintes-Maries-de-la-Mer",
}

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("kayak")
