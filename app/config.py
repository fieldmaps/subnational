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
FORCE_PMTILES: bool = os.getenv("FORCE_PMTILES", "").upper() in _BOOL_VALS

PKG_DIR = Path(__file__).parent
TMP_DIR = PKG_DIR.parent / "tmp"

CATALOG_DIR = PKG_DIR.parent / "catalog"
BUILD_DB = TMP_DIR / "build.duckdb"

# iso3s whose published layer cod-ab must not replace (deeper, matches Mapbox).
KEEP = {"mda", "pol", "svk"}
# cod-ab iso3s published as one extended layer per ADM0 clip part.
PARTS = {"geo": ("GEO_1", "GEO_2", "GEO_3"), "jam": ("JAM_1",), "zaf": ("ZAF_1",)}
TIERS = ("extended", "original")
MAX_LVL = 4

GEOMS = ("polygons", "lines", "points")
HTTP_TIMEOUT = 60
