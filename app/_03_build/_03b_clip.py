"""Clip the source to ADM0 boundaries and dissolve up admin levels, per country.

Only adm{1..4} are produced; adm0 is out of scope. Each country is clipped to its
ADM0 boundary (adm0_bounds, one row per country) and dissolved per level, then
appended — the per-country loop bounds peak memory to a single country. With a
sane-resolution clip boundary this is a plain two-pass ST_Within/ST_Intersection
clip; no subdivision or tiling is required.
"""

import duckdb

from .utils import describe, src_id_cols, src_meta_cols


def clip_and_aggregate(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm{1..4}_polygons one country at a time."""
    src_cols = describe(conn, "src")

    # Empty target tables with the correct schema (stable INSERT targets).
    for lvl in range(1, 5):
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE adm{lvl}_polygons AS
            SELECT iso3,
                   {_attr_select(src_cols, lvl)},
                   ST_Multi(ST_Union_Agg(geom))::GEOMETRY AS geom
            FROM src
            WHERE false
            GROUP BY ALL
        """)

    rows = conn.execute("SELECT DISTINCT iso3 FROM src ORDER BY iso3").fetchall()
    for (iso3,) in rows:
        _process_country(conn, iso3, src_cols)


def _process_country(
    conn: duckdb.DuckDBPyConnection,
    iso3: str,
    src_cols: list[str],
) -> None:
    """Clip one country's source rows and append its adm{1..4}_polygons rows."""
    conn.execute(
        "CREATE OR REPLACE TEMP TABLE src_one AS SELECT * FROM src WHERE iso3 = ?",
        [iso3],
    )
    conn.execute(
        "CREATE OR REPLACE TEMP TABLE clip_one AS "
        "SELECT geom FROM adm0_bounds WHERE iso3 = ?",
        [iso3],
    )

    # Two-pass clip: rows fully within the boundary pass through unchanged; rows
    # that cross it are intersected. Both passes cross-join the single-row clip_one.
    conn.execute("""--sql
        CREATE OR REPLACE TEMP TABLE src_clipped AS
        SELECT s.* EXCLUDE (geom), s.geom
        FROM src_one s, clip_one c
        WHERE ST_Within(s.geom, c.geom)
          AND ST_IsValid(s.geom)
        UNION ALL
        SELECT s.* EXCLUDE (geom),
               ST_Multi(ST_CollectionExtract(
                   ST_Intersection(s.geom, c.geom), 3
               ))::GEOMETRY AS geom
        FROM src_one s, clip_one c
        WHERE ST_Intersects(s.geom, c.geom)
          AND NOT ST_Within(s.geom, c.geom)
          AND ST_IsValid(s.geom)
    """)
    for lvl in range(1, 5):
        conn.execute(f"""--sql
            INSERT INTO adm{lvl}_polygons
            SELECT iso3,
                   {_attr_select(src_cols, lvl)},
                   ST_Multi(ST_Union_Agg(geom))::GEOMETRY AS geom
            FROM src_clipped
            WHERE adm{lvl}_id IS NOT NULL
            GROUP BY ALL
        """)


def _attr_select(src_cols: list[str], level: int) -> str:
    """Return the comma-joined src ID/meta columns present in src for a level."""
    attr_cols = [c for c in src_id_cols(level) + src_meta_cols() if c in src_cols]
    return ", ".join(f'"{c}"' for c in attr_cols)
