"""
AWS helpers: S3 upload and RDS PostgreSQL load.

This module is only imported when run_s3=True or run_rds=True.
boto3, sqlalchemy, and psycopg2 are optional dependencies — only
needed if you use the AWS load steps.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

from kayak.config import (
    AWS_REGION,
    RDS_DB_NAME,
    RDS_HOST,
    RDS_PASSWORD,
    RDS_PORT,
    RDS_SCHEMA,
    RDS_USER,
    S3_BUCKET_NAME,
    S3_CLEAN_PREFIX,
    S3_RAW_PREFIX,
    logger,
)

# ── Validation ────────────────────────────────────────────────────────────────

def _require(value: str | None, var_name: str) -> str:
    """Raise a clear error if an environment variable is missing."""
    if not value or not str(value).strip():
        raise ValueError(f"Missing required environment variable: {var_name}")
    return str(value).strip()


def _validate_sql_identifier(name: str) -> str:
    """Guard against SQL injection in schema/table names."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


# ── S3 ────────────────────────────────────────────────────────────────────────

def _get_s3_client():
    try:
        import boto3  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("boto3 is required for S3 uploads: pip install boto3") from exc
    return boto3.client("s3", region_name=AWS_REGION)


def upload_file_to_s3(file_path: str | Path, prefix: str, filename: str) -> None:
    """Upload *file_path* to S3 under *prefix/filename*."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    bucket  = _require(S3_BUCKET_NAME, "S3_BUCKET_NAME")
    key     = f"{prefix.strip('/')}/{filename}"
    client  = _get_s3_client()

    try:
        client.upload_file(str(file_path), bucket, key)
        logger.info("S3 upload: s3://%s/%s", bucket, key)
    except Exception as exc:
        logger.error("S3 upload failed for %s: %s", key, exc)
        raise


def upload_all_csvs_to_s3() -> None:
    """Upload all pipeline output CSV files to S3."""
    from kayak.config import DATA_DIR

    files = {
        S3_RAW_PREFIX:   ["cities_geocoded.csv", "cities_weather.csv", "hotels_osm.csv"],
        S3_CLEAN_PREFIX: ["cities_enriched.csv", "top_hotels.csv"],
    }
    for prefix, names in files.items():
        for name in names:
            path = DATA_DIR / name
            if path.exists():
                upload_file_to_s3(path, prefix, name)
            else:
                logger.warning("CSV not found, skipping S3 upload: %s", path)


# ── RDS ───────────────────────────────────────────────────────────────────────

def _build_connection_url() -> str:
    """Build a SQLAlchemy PostgreSQL URL with URL-encoded password."""
    host     = _require(RDS_HOST,     "RDS_HOST")
    port     = _require(RDS_PORT,     "RDS_PORT")
    db_name  = _require(RDS_DB_NAME,  "RDS_DB_NAME")
    user     = _require(RDS_USER,     "RDS_USER")
    password = _require(RDS_PASSWORD, "RDS_PASSWORD")
    # quote_plus handles special chars (@, /, %) in the password
    return f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:{port}/{db_name}"


def _get_engine():
    try:
        from sqlalchemy import create_engine  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "sqlalchemy and psycopg2-binary are required for RDS: "
            "pip install sqlalchemy psycopg2-binary"
        ) from exc
    return create_engine(_build_connection_url(), future=True)


def test_rds_connection() -> bool:
    """Return True if a SELECT 1 succeeds, False otherwise."""
    from sqlalchemy import text  # type: ignore[import]
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("RDS connection OK")
        return True
    except Exception as exc:
        logger.error("RDS connection failed: %s", exc)
        return False


def load_dataframe_to_rds(
    df: pd.DataFrame,
    table_name: str,
    if_exists: str = "replace",
) -> None:
    """Write *df* to the RDS table *schema.table_name*."""
    schema = _validate_sql_identifier(RDS_SCHEMA)
    table  = _validate_sql_identifier(table_name)
    engine = _get_engine()

    df.to_sql(table, engine, schema=schema, if_exists=if_exists, index=False)
    logger.info("RDS load: %d rows → %s.%s", len(df), schema, table)


# ── Orchestration ─────────────────────────────────────────────────────────────

def run_aws_load(
    city_df: pd.DataFrame,
    hotel_df: pd.DataFrame,
    run_s3: bool = True,
    run_rds: bool = True,
) -> None:
    """Upload to S3 and/or load into RDS."""
    if run_s3:
        logger.info("Uploading CSV files to S3 …")
        upload_all_csvs_to_s3()

    if run_rds:
        logger.info("Loading data into RDS …")
        if not test_rds_connection():
            raise ConnectionError("Cannot reach RDS — check .env credentials")

        load_dataframe_to_rds(city_df,  "dim_destinations")
        load_dataframe_to_rds(hotel_df, "fact_hotels")
        logger.info("RDS load complete")
