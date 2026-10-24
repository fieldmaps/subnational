"""Shared paths and constants used across pipeline stages."""

import os
from pathlib import Path

PARQUET_OPTS = "(COMPRESSION ZSTD, COMPRESSION_LEVEL 15, GEOPARQUET_VERSION V2)"
os.environ["OGR_ORGANIZE_POLYGONS"] = "ONLY_CCW"

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

GEOMS = ("polygons", "lines", "points")
HTTP_TIMEOUT = 60
WLD = os.getenv("WLD", "intl")
