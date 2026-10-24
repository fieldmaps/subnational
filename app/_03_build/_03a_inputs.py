"""Load the per-iso3 input paths and build the ADM0 clip boundary."""

import duckdb

from app.config import CATALOG_DIR

from .config import (
    ADM0_BASE,
    ADM0_DISAGGREGATED,
    ADM0_HUMANITARIAN,
    ADM0_LOCAL,
    CLIP_ADD,
    CLIP_DROP,
)


def input_paths(tier: str) -> list[str]:
    """Return every catalog/{tier}/*/*_{tier}.parquet path, sorted."""
    return sorted(str(p) for p in (CATALOG_DIR / tier).glob(f"*/*_{tier}.parquet"))


def load_adm0(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm0_clip, adm0_wld (one row per iso_3), and adm0_bounds (per match key).

    adm0_clip is the humanitarian view with CLIP_DROP swapped for CLIP_ADD.
    """
    drop = ", ".join(f"'{s}'" for s in CLIP_DROP)
    add = ", ".join(f"'{s}'" for s in CLIP_ADD)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE adm0_clip AS
        SELECT * FROM read_parquet('{adm0_path(ADM0_HUMANITARIAN)}')
        WHERE adm0_src NOT IN ({drop})
        UNION ALL BY NAME
        SELECT * FROM read_parquet('{adm0_path(ADM0_DISAGGREGATED)}')
        WHERE adm0_src IN ({add})
    """)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE adm0_wld AS
        SELECT * EXCLUDE (geometry) FROM adm0_clip
        QUALIFY row_number() OVER (PARTITION BY iso_3 ORDER BY adm0_id) = 1
    """)
    conn.execute("""--sql
        CREATE OR REPLACE TABLE adm0_bounds AS
        SELECT adm0_src AS iso3, ST_Union_Agg(geometry)::GEOMETRY AS geom
        FROM adm0_clip
        GROUP BY adm0_src
        UNION ALL
        SELECT iso_3 AS iso3, ST_Union_Agg(geometry)::GEOMETRY AS geom
        FROM adm0_clip
        WHERE iso_3 != adm0_src
        GROUP BY iso_3
    """)


def adm0_path(rel: str) -> str:
    """Return the local adm0-generator catalog file if present, else its URL."""
    local = ADM0_LOCAL / rel
    return str(local) if local.exists() else f"{ADM0_BASE}/{rel}"
