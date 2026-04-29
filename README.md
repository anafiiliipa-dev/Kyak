# 🗺️ Kayak Destination Recommender — French Cities

> A data engineering pipeline that collects, scores, and ranks the best French travel destinations based on real-time weather and hotel data.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![AWS](https://img.shields.io/badge/AWS-S3%20%2B%20RDS-orange?logo=amazonaws)](https://aws.amazon.com/)
[![Data Source](https://img.shields.io/badge/Data-OpenStreetMap%20%7C%20Open--Meteo-green)](https://openstreetmap.org/)

---

## Overview

This project builds an end-to-end data pipeline to recommend the best French cities to visit. It answers the question: **which of 35 French destinations has the best weather and nearby hotel options right now?**

The pipeline collects data entirely from free, open APIs — no paid services required for local execution.

---

## Architecture

```
35 French cities
       │
       ▼
┌──────────────┐    Nominatim API     ┌─────────────────────┐
│  Geocoding   │ ─────────────────▶  │  cities_geocoded.csv │
└──────────────┘                      └─────────────────────┘
       │
       ▼
┌──────────────┐    Open-Meteo API    ┌────────────────────┐
│   Weather    │ ─────────────────▶  │ cities_weather.csv  │
└──────────────┘                      └────────────────────┘
       │
       ▼
┌──────────────┐    Overpass API      ┌─────────────────┐
│    Hotels    │ ─────────────────▶  │  hotels_osm.csv  │
└──────────────┘                      └─────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  Enrichment & Scoring                                │
│  • Weather score = temp × 2 − rain × 1.5 − pop × 0.2│
│  • Hotel score   = stars × 10 − distance_km × 2     │
└──────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────┐   ┌──────────────────┐
│  cities_enriched │   │   top_hotels.csv │
│  .csv (ranked)   │   │   (top 20)       │
└──────────────────┘   └──────────────────┘
       │ (optional)
       ▼
┌────────────────────────────────┐
│  AWS S3  +  AWS RDS/PostgreSQL │
│  dim_destinations / fact_hotels│
└────────────────────────────────┘
```

---

## Project Structure

```
Kyak/
├── notebooks/
│   ├── 01-Plan_your_trip_with_Kayak.ipynb   # Project brief (read first)
│   └── kyak.ipynb                           # Main pipeline notebook
├── data/                                    # Sample output CSV files
│   ├── cities_geocoded.csv
│   ├── cities_weather.csv
│   ├── cities_enriched.csv
│   ├── hotels_osm.csv
│   └── top_hotels.csv
├── tests/
│   └── test_pipeline.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.10+
- A virtual environment (recommended)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/anafiiliipa-dev/Kyak.git
   cd Kyak
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate    # Linux / macOS
   .venv\Scripts\activate       # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure secrets (AWS only — optional)**
   ```bash
   cp .env.example .env
   # Edit .env with your AWS credentials if using S3/RDS
   ```

---

## Running the Pipeline

Open `notebooks/kyak.ipynb` in Jupyter or VS Code and run cells in order.

- **Local only** (no AWS required): `main(run_s3=False, run_rds=False)`
- **With S3 upload**: `main(run_s3=True, run_rds=False)`
- **Full pipeline**: `main(run_s3=True, run_rds=True)`

Output CSV files are saved to the `data/` directory.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Data Sources

| Source | API | Usage |
|---|---|---|
| [Nominatim](https://nominatim.openstreetmap.org/) | Free, rate-limited (1 req/s) | City geocoding |
| [Open-Meteo](https://open-meteo.com/) | Free, no auth | 7-day weather forecast |
| [Overpass API](https://overpass-api.de/) | Free | Hotel locations from OpenStreetMap |

---

## AWS Setup (Optional)

The pipeline optionally uploads clean data to **S3** and loads it into **RDS PostgreSQL**.

Required environment variables (see `.env.example`):

| Variable | Description |
|---|---|
| `S3_BUCKET_NAME` | Name of your S3 bucket |
| `AWS_REGION` | AWS region (e.g. `eu-west-3`) |
| `RDS_HOST` | RDS endpoint hostname |
| `RDS_PORT` | PostgreSQL port (default: `5432`) |
| `RDS_DB_NAME` | Database name |
| `RDS_USER` | Database username |
| `RDS_PASSWORD` | Database password |
| `RDS_SCHEMA` | Schema name (default: `public`) |

---

## Author

**Ana Gouveia — DSFS-OD-14 cohort**
