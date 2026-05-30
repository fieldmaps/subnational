"""Load the source table and the ADM0 clip boundary into the build DuckDB.

Only adm{1..4} are produced by this stage; adm0 comes from a separate pipeline.
The ADM0 layer is used solely as the clip boundary (adm0_bounds, one row per
country). The boundary is grid-subdivided per country in _03b so no single GEOS
clip ever sees the full multi-million-vertex coastline — DuckDB OOMs on that.
"""

import duckdb

from app.config import PREPARE_DB, WLD

from .config import ADM0_BASE


def load_source(conn: duckdb.DuckDBPyConnection) -> None:
    """Load the global admin table from tmp/prepare.duckdb into src.

    Sorted by iso3 so the per-country `WHERE iso3 = ?` filters in the clip stage
    prune row groups via min/max statistics instead of rescanning the whole table.
    """
    conn.execute(f"ATTACH '{PREPARE_DB}' AS prepare (READ_ONLY)")
    conn.execute(
        "CREATE OR REPLACE TABLE src AS SELECT * FROM prepare.admin ORDER BY iso3"
    )
    conn.execute("DETACH prepare")


def load_adm0(conn: duckdb.DuckDBPyConnection) -> None:
    """Load ADM0 world-view attributes and the per-country clip boundary.

    adm0_wld: one row per country (world-view attributes, no geometry), deduplicated
    to one row per iso_3 so the left-join onto adm{1..4} in _03e can't fan out
    countries with several ADM0 features (e.g. ESP, UMI).

    adm0_bounds: one row per country, the union of its ADM0 clip features — the clip
    boundary subdivided and applied in _03b.
    """
    poly_url = _adm0_url("polygons")
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE adm0_wld AS
        SELECT * EXCLUDE (geometry, geometry_bbox)
        FROM read_parquet('{poly_url}')
        QUALIFY row_number() OVER (PARTITION BY iso_3 ORDER BY adm0_id) = 1
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE adm0_bounds AS
        SELECT iso_3 AS iso3, ST_Union_Agg(geometry)::GEOMETRY AS geom
        FROM read_parquet('{clip_url()}')
        GROUP BY iso_3
    """)


def clip_url() -> str:
    """Return the ADM0 clip-boundary parquet URL."""
    return _adm0_url("clip")


def _adm0_url(geom: str) -> str:
    return f"{ADM0_BASE}/{WLD}/adm0_{geom}.parquet"
