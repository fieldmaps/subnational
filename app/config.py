"""Shared paths and constants used across pipeline stages."""

import os
from pathlib import Path

from dotenv import load_dotenv

PARQUET_OPTS = "(COMPRESSION ZSTD, COMPRESSION_LEVEL 15, GEOPARQUET_VERSION V2)"
os.environ["OGR_ORGANIZE_POLYGONS"] = "ONLY_CCW"

load_dotenv(Path(__file__).parent.parent / ".env")

_BOOL_VALS = ("YES", "ON", "TRUE", "1")
DEBUG: bool = os.getenv("DEBUG", "").upper() in _BOOL_VALS
PUSH: bool = os.getenv("PUSH", "").upper() in _BOOL_VALS

PKG_DIR = Path(__file__).parent
TMP_DIR = PKG_DIR.parent / "tmp"
OUTPUTS_DIR = PKG_DIR.parent / "outputs"

CATALOG_DIR = PKG_DIR.parent / "catalog"
SOURCES_TABLE = TMP_DIR / "sources" / "sources.parquet"
BUILD_DB = TMP_DIR / "build.duckdb"
EDGE_MATCHED_DIR = OUTPUTS_DIR / "edge-matched"

# Catalog source folders, highest build priority first.
SOURCES = ("cod-ab", "erm", "cod-ab-legacy", "geoboundaries")
# Per-iso3 src overriding SOURCES order, where it is deeper and matches Mapbox.
PREFER = {"mda": "erm", "pol": "erm", "svk": "erm"}
TIERS = ("extended", "original")
MAX_LVL = 4

GEOMS = ("polygons", "lines", "points")
HTTP_TIMEOUT = 60
WLD = os.getenv("WLD", "intl")
