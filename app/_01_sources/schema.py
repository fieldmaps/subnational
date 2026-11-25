"""cod-ab extended schema shared by every extended-tier collection."""

import json
from logging import getLogger
from pathlib import Path

import duckdb
from topo_tools.api import edge_extend, topo_clean, topo_detect

from app.adm0 import adm0_clip_sql
from app.config import CATALOG_DIR, PARQUET_OPTS, TMP_DIR

from .utils import catalog_path

logger = getLogger(__name__)

# Latin-script names, preferred when a source leaves adm{n}_name empty.
LATIN = r"[\p{Latin}\p{Common}\p{Inherited}]+"
_LEVEL_COLS = ("name", "name1", "name2", "name3", "pcode")
# Schema column <- source column read when a source lacks the schema name.
_FALLBACK = {"valid_from": "valid_on"}
_TAIL = (
    ("valid_from", "DATE"),
    ("valid_to", "DATE"),
    ("version", "VARCHAR"),
    ("lang", "VARCHAR"),
    ("lang1", "VARCHAR"),
    ("lang2", "VARCHAR"),
    ("lang3", "VARCHAR"),
    ("iso2", "VARCHAR"),
    ("iso3", "VARCHAR"),
    ("geometry", "GEOMETRY"),
)
META_COLS = (
    ("key", "VARCHAR"),
    ("tier", "VARCHAR"),
    ("iso3", "VARCHAR"),
    ("src", "VARCHAR"),
    ("src_lvl", "INTEGER"),
    ("src_lang", "VARCHAR"),
    ("src_lang1", "VARCHAR"),
    ("src_lang2", "VARCHAR"),
    ("src_date", "DATE"),
    ("src_update", "DATE"),
    ("src_name", "VARCHAR"),
    ("src_name1", "VARCHAR"),
    ("src_lic", "VARCHAR"),
    ("src_url", "VARCHAR"),
    ("src_grp", "VARCHAR"),
    ("via", "VARCHAR"),
    ("via_checksum", "VARCHAR"),
)
_ROW = "STRUCT(" + ", ".join(f'"{c}" {t}' for c, t in META_COLS) + ")"
# One row per published (key, tier), read from every catalog/source sidecar.
SOURCES_SQL = f"""
    SELECT *, split_part(key, '_', 1) AS base
    FROM (
        SELECT unnest(rows, recursive := true)
        FROM read_json(
            '{CATALOG_DIR}/source/*/*_metadata.json',
            columns = {{'rows': '{_ROW}[]'}}
        )
    )
    ORDER BY tier, key
"""


def columns(lvl: int) -> list[tuple[str, str]]:
    """Return the ordered (name, type) columns of a level-`lvl` extended layer."""
    cols = [(f"adm{n}_{c}", "VARCHAR") for n in range(lvl, -1, -1) for c in _LEVEL_COLS]
    return cols + list(_TAIL)


# Some legacy extended layers reach past the poles or antimeridian; clip to lon/lat.
_CLAMP = """CASE WHEN ST_XMin(geometry) < -180 OR ST_XMax(geometry) > 180
    OR ST_YMin(geometry) < -90 OR ST_YMax(geometry) > 90
    THEN ST_Intersection(geometry, ST_MakeEnvelope(-180, -90, 180, 90))
    ELSE geometry END AS geometry"""


def conform(
    conn: duckdb.DuckDBPyConnection, select_sql: str, lvl: int, dest: Path
) -> None:
    """Write `select_sql` to dest in the extended schema, NULL-filling gaps."""
    have = {row[0] for row in conn.execute(f"DESCRIBE {select_sql}").fetchall()}
    src = {c: c if c in have else _FALLBACK.get(c) for c, _ in columns(lvl)}
    parts = ", ".join(
        _CLAMP
        if c == "geometry"
        else f'CAST({f'"{src[c]}"' if src[c] in have else "NULL"} AS {t}) AS "{c}"'
        for c, t in columns(lvl)
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(
        f"COPY (SELECT {parts} FROM ({select_sql})) TO '{dest}' {PARQUET_OPTS}"
    )


def conform_extended(
    conn: duckdb.DuckDBPyConnection, select_sql: str, lvl: int, dest: Path
) -> None:
    """Conform an extended layer, then topo_clean it if topo_detect finds defects."""
    conform(conn, select_sql, lvl, dest)
    work = TMP_DIR / "sources" / "coverage"
    work.mkdir(parents=True, exist_ok=True)
    issues = work / f"{dest.stem}_issues.parquet"
    topo_detect(dest, issues, threads=4)
    if not conn.execute(f"SELECT count(*) FROM '{issues}'").fetchall()[0][0]:
        return
    logger.warning("%s: coverage defects, cleaning", dest.name)
    cut = work / f"{dest.stem}_cut.parquet"
    _cut_enclaves(conn, dest, cut)
    clean = work / f"{dest.stem}_clean.parquet"
    topo_clean(cut, clean, work / f"{dest.stem}_clean_issues.parquet", threads=4)
    conform(conn, f"SELECT * FROM read_parquet('{clean}')", lvl, dest)


def _cut_enclaves(conn: duckdb.DuckDBPyConnection, src: Path, dest: Path) -> None:
    """Write src with each unit's part lying wholly inside another unit cut from it.

    topo_clean gives such an overlap to the enclosing unit; the cut keeps the exclave.
    """
    conn.execute(f"""--sql
        CREATE OR REPLACE TEMP TABLE _units AS
        SELECT row_number() OVER () AS _rid, * FROM read_parquet('{src}');
        CREATE OR REPLACE TEMP TABLE _cuts AS
        WITH parts AS (
            SELECT _rid, unnest(ST_Dump(geometry)).geom AS p FROM _units
        )
        SELECT o._rid, ST_Union_Agg(a.p) AS g
        FROM parts a
        JOIN parts o
          ON a._rid <> o._rid
         AND ST_Within(a.p, o.p)
         AND NOT ST_Within(o.p, a.p)
        GROUP BY o._rid;
    """)
    n = conn.execute("SELECT count(*) FROM _cuts").fetchall()[0][0]
    if n:
        logger.info("%s: cut %d enclosing unit(s) around exclaves", src.name, n)
    conn.execute(f"""--sql
        COPY (
            SELECT u.* EXCLUDE (_rid) REPLACE (
                coalesce(ST_Difference(u.geometry, c.g), u.geometry) AS geometry
            )
            FROM _units u LEFT JOIN _cuts c USING (_rid)
        ) TO '{dest}' {PARQUET_OPTS}
    """)


def split_extended(
    conn: duckdb.DuckDBPyConnection, original: str, lvl: int, parts: tuple, work: Path
) -> None:
    """Write one extended layer per ADM0 clip part from the units inside it."""
    work.mkdir(parents=True, exist_ok=True)
    for part in parts:
        subset = work / f"{part.lower()}.parquet"
        conn.execute(
            f"""--sql
            COPY (
                SELECT o.* FROM ({original}) o
                JOIN ({adm0_clip_sql()}) a
                  ON a.adm0_src = ?
                 AND ST_Within(ST_PointOnSurface(o.geometry), a.geometry)
            ) TO '{subset}' {PARQUET_OPTS}
        """,
            [part],
        )
        extended = subset.with_name(f"{part.lower()}_extended.parquet")
        edge_extend(subset, extended)
        select = f"SELECT * FROM read_parquet('{extended}')"
        conform_extended(conn, select, lvl, catalog_path("extended", part.lower()))


def write_meta(meta: dict, dest: Path) -> None:
    """Upsert one (key, tier) row into the collection's {base}_metadata.json."""
    rows = json.loads(dest.read_text())["rows"] if dest.exists() else []
    rows = [r for r in rows if (r["key"], r["tier"]) != (meta["key"], meta["tier"])]
    rows.append({c: meta.get(c) for c, _ in META_COLS})
    rows.sort(key=lambda r: (r["key"], r["tier"]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"rows": rows}, indent=2, default=lambda v: v.isoformat()[:10])
        + "\n"
    )
