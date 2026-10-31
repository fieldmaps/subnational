"""cod-ab extended schema shared by every extended-tier collection."""

import json
from pathlib import Path

import duckdb

from app.config import PARQUET_OPTS

_LEVEL_COLS = ("name", "name1", "name2", "name3", "pcode")
_TAIL = (
    ("valid_on", "TIMESTAMP"),
    ("valid_to", "TIMESTAMP"),
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
)


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
    parts = ", ".join(
        _CLAMP
        if c == "geometry"
        else f'CAST({f'"{c}"' if c in have else "NULL"} AS {t}) AS "{c}"'
        for c, t in columns(lvl)
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(
        f"COPY (SELECT {parts} FROM ({select_sql})) TO '{dest}' {PARQUET_OPTS}"
    )


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
