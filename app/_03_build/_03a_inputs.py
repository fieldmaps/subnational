"""Stage the selected per-iso3 inputs and build the ADM0 clip boundary."""

from pathlib import Path

import duckdb

from app._01_sources.utils import catalog_path
from app.config import PARQUET_OPTS, SOURCES_TABLE, TMP_DIR

from .config import (
    ADM0_BASE,
    ADM0_DISAGGREGATED,
    ADM0_HUMANITARIAN,
    ADM0_LOCAL,
    CLIP_ADD,
    CLIP_DROP,
)
from .utils import ADMIN_SCHEMA_SQL, id_gen_ctas_sql

STAGE_DIR = TMP_DIR / "build" / "inputs"
_META = (
    "src_lvl",
    "src_lang",
    "src_lang1",
    "src_lang2",
    "src_date",
    "src_update",
    "src_name",
    "src_name1",
    "src_lic",
    "src_url",
    "src_grp",
)


def input_paths(tier: str) -> list[str]:
    """Return the selected {tier} parquet paths, sorted by key."""
    return [str(catalog_path(src, tier, key)) for src, key in _selected(tier)]


def stage_extended(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Map each selected extended layer onto the build's admin schema; return paths.

    iso3 is the upper-cased key so multi-extent keys (e.g. GEO_1) match adm0_bounds.
    """
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for src, key in _selected("extended"):
        meta = conn.execute(
            f"SELECT {', '.join(_META)} FROM read_parquet('{SOURCES_TABLE}') "
            "WHERE tier = 'extended' AND src = ? AND key = ?",
            [src, key],
        ).fetchall()[0]
        levels = ", ".join(
            f"adm{n}_pcode AS adm{n}_id, adm{n}_pcode AS adm{n}_src, "
            f"adm{n}_name, adm{n}_name1, adm{n}_name2"
            for n in range(meta[0] + 1)
        )
        conn.execute(ADMIN_SCHEMA_SQL)
        conn.execute(
            f"""--sql
            INSERT INTO admin BY NAME
            SELECT upper(?) AS iso3, {levels},
                   ? AS src_lvl, ? AS src_lang, ? AS src_lang1, ? AS src_lang2,
                   coalesce(CAST(valid_on AS DATE), ?) AS src_date,
                   ? AS src_update, ? AS src_name, ? AS src_name1, ? AS src_lic,
                   ? AS src_url, ? AS src_grp, geometry AS geom
            FROM read_parquet('{catalog_path(src, "extended", key)}')
        """,
            [key, *meta],
        )
        conn.execute(id_gen_ctas_sql())
        dest = STAGE_DIR / f"{key}.parquet"
        _write_clamped(conn, dest)
        paths.append(str(dest))
    return paths


def _selected(tier: str) -> list[tuple[str, str]]:
    """Return (src, key) of the selected rows of one tier, sorted by key."""
    with duckdb.connect() as conn:
        return conn.execute(
            f"SELECT src, key FROM read_parquet('{SOURCES_TABLE}') "
            "WHERE selected AND tier = ? ORDER BY key",
            [tier],
        ).fetchall()


def _write_clamped(conn: duckdb.DuckDBPyConnection, dest: Path) -> None:
    """Write the `admin` table to dest, clamped to the lon/lat range."""
    conn.execute(f"""--sql
        COPY (
            SELECT * EXCLUDE (geom), geom AS geometry FROM (
                SELECT * REPLACE (
                    CASE WHEN ST_XMin(geom) < -180 OR ST_XMax(geom) > 180
                           OR ST_YMin(geom) < -90 OR ST_YMax(geom) > 90
                    THEN ST_CollectionExtract(ST_Intersection(
                        geom, ST_MakeEnvelope(-180, -90, 180, 90)), 3)
                    ELSE geom END AS geom
                )
                FROM admin
            )
            WHERE NOT ST_IsEmpty(geom)
        ) TO '{dest}' {PARQUET_OPTS}
    """)


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
    """Return the local international catalog file if present, else its URL."""
    local = ADM0_LOCAL / rel
    return str(local) if local.exists() else f"{ADM0_BASE}/{rel}"
