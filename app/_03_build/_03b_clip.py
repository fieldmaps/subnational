"""Clip the source to the ADM0 boundary and dissolve up admin levels, per country.

Only adm{1..4} are produced; adm0 is out of scope. For each country the boundary
(adm0_bounds) is grid-subdivided into small lossless pieces (btile) — the union of
the pieces is exactly the boundary — and each source polygon is clipped against the
pieces its bbox overlaps, then dissolved per level. Clipping against small pieces,
and joining on scalar bbox predicates rather than ST_Intersects (which DuckDB plans
as SPATIAL_JOIN, reserving ~1x RAM), keeps peak memory bounded with no simplification
and runs fast on a single core.
"""

import math

import duckdb

from .config import CLIP_CELL
from .utils import describe, src_id_cols, src_meta_cols


def clip_and_aggregate(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm{1..4}_polygons one country at a time."""
    src_cols = describe(conn, "src")

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
    _subdivide_boundary(conn)

    # Clip each source polygon against the boundary pieces its bbox overlaps (scalar
    # bbox join → no SPATIAL_JOIN), then union the pieces back per source row.
    conn.execute("""--sql
        CREATE OR REPLACE TEMP TABLE src_clipped AS
        SELECT s.* EXCLUDE (geom),
               ST_Multi(ST_CollectionExtract(
                   ST_Union_Agg(ST_Intersection(s.geom, b.geom)), 3
               ))::GEOMETRY AS geom
        FROM src_one s
        JOIN btile b
          ON ST_XMax(b.geom) >= ST_XMin(s.geom) AND ST_XMin(b.geom) <= ST_XMax(s.geom)
         AND ST_YMax(b.geom) >= ST_YMin(s.geom) AND ST_YMin(b.geom) <= ST_YMax(s.geom)
        GROUP BY ALL
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


def _subdivide_boundary(conn: duckdb.DuckDBPyConnection) -> None:
    """Grid-subdivide clip_one's boundary into temp table btile, strip by strip.

    Each vertical strip is one bounded ST_Intersection(boundary, strip_rect); the
    strip (small) is split into row cells. Looping strips bounds peak memory to a
    single strip rather than the whole multi-million-vertex boundary, losslessly.
    """
    bbox = conn.execute(
        "SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) "
        "FROM clip_one"
    ).fetchone()
    x0, y0, _x1, y1 = bbox or (0.0, 0.0, 0.0, 0.0)
    ny = max(1, math.ceil((y1 - y0) / CLIP_CELL))

    # Only the longitude cells that actually contain boundary, derived from the
    # exploded part bboxes — skips empty ocean bands so antimeridian-spanning
    # countries (USA/RUS, bbox ~360 wide) don't iterate hundreds of empty strips.
    occupied = conn.execute(
        f"""--sql
        WITH parts AS (SELECT (UNNEST(ST_Dump(geom))).geom AS g FROM clip_one)
        SELECT DISTINCT UNNEST(range(
            CAST(floor((ST_XMin(g) - {x0}) / {CLIP_CELL}) AS INTEGER),
            CAST(floor((ST_XMax(g) - {x0}) / {CLIP_CELL}) AS INTEGER) + 1
        )) AS i
        FROM parts
        ORDER BY i
        """
    ).fetchall()

    conn.execute("CREATE OR REPLACE TEMP TABLE btile (geom GEOMETRY)")
    for (i,) in occupied:
        sx0, sx1 = x0 + i * CLIP_CELL, x0 + (i + 1) * CLIP_CELL
        conn.execute(f"""--sql
            INSERT INTO btile
            WITH strip AS (
                SELECT ST_Intersection(
                    geom, ST_MakeEnvelope({sx0}, {y0}, {sx1}, {y1})
                ) AS g FROM clip_one
            ),
            gy AS (SELECT UNNEST(range({ny})) AS j)
            SELECT geom FROM (
                SELECT ST_Intersection(
                    strip.g,
                    ST_MakeEnvelope(
                        {sx0}, {y0} + j * {CLIP_CELL},
                        {sx1}, {y0} + (j + 1) * {CLIP_CELL}
                    )
                ) AS geom
                FROM strip, gy
                WHERE NOT ST_IsEmpty(strip.g)
            ) WHERE NOT ST_IsEmpty(geom)
        """)


def _attr_select(src_cols: list[str], level: int) -> str:
    """Return the comma-joined src ID/meta columns present in src for a level."""
    attr_cols = [c for c in src_id_cols(level) + src_meta_cols() if c in src_cols]
    return ", ".join(f'"{c}"' for c in attr_cols)
