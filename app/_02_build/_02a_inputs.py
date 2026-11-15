"""Write the per-key ADM0 parent rows and stage each published extended layer."""

import re
from contextlib import closing
from pathlib import Path

import duckdb
from topo_tools.api import code_create

from app._01_sources.schema import LATIN, META_COLS, SOURCES_SQL, columns
from app._01_sources.utils import catalog_path
from app.adm0 import ADM0_HUMANITARIAN, adm0_clip_sql, adm0_path
from app.config import MAX_LVL, PARQUET_OPTS
from app.utils import get_conn

from .config import ADM0_FILL, BUILD_DIR, CODE_FIELD, MATCH_KEY, NAME_FIELD, WLD_COLS

PARENT = BUILD_DIR / "parent.parquet"
# src_lang..2 repeat lang..lang2, so the matched layers leave them out.
_META = tuple(
    (c, t)
    for c, t in META_COLS
    if c.startswith("src_") and not c.startswith("src_lang")
)


def sources() -> dict[str, tuple]:
    """Return each published extended key's src_* sidecar values, by key."""
    names = ", ".join(c for c, _ in _META)
    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"SELECT key, {names} FROM ({SOURCES_SQL}) "
            "WHERE tier = 'extended' ORDER BY key"
        ).fetchall()
    return {key: tuple(meta) for key, *meta in rows}


def staged_columns() -> list[tuple[str, str]]:
    """Return every staged (column, type), with code_create's adm{n}_id columns.

    Leaves out the source's version and iso2/iso3; the overlay's codes replace them.
    """
    cols = [
        (c, t)
        for name, t in columns(MAX_LVL)
        if name not in ("iso2", "iso3", "version")
        for c in ((f"{name[:4]}_id", name) if _is_id_slot(name) else (name,))
    ]
    return [(MATCH_KEY, "VARCHAR"), *cols, *_META]


def write_parent(keys: list[str]) -> None:
    """Write PARENT: the clip ADM0 merged per match key, with world-view columns.

    A part keeps its own key when an input has it, else merges under its iso3.
    Fill columns come from the part's own row: unmatched keys are single parts.
    """
    wld = ", ".join(f"w.{c}" for c in WLD_COLS)
    part = [c for c in ADM0_FILL.values() if c not in WLD_COLS]
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    with closing(get_conn()) as conn:
        conn.execute(
            f"""--sql
            COPY (
                WITH clip AS ({adm0_clip_sql()}), wld AS (
                    SELECT * EXCLUDE (geometry)
                    FROM read_parquet('{adm0_path(ADM0_HUMANITARIAN)}')
                    QUALIFY row_number() OVER (PARTITION BY iso3 ORDER BY adm0_id) = 1
                ), keyed AS (
                    SELECT CASE WHEN list_contains($keys, adm0_src) THEN adm0_src
                                WHEN list_contains($keys, iso3) THEN iso3
                                ELSE adm0_src END AS {MATCH_KEY},
                           iso3, {", ".join(part)}, geometry
                    FROM clip
                ), merged AS (
                    SELECT {MATCH_KEY}, arg_min(iso3, adm0_id) AS iso3,
                           {", ".join(f"arg_min({c}, adm0_id) AS {c}" for c in part)},
                           ST_Union_Agg(geometry)::GEOMETRY AS geom
                    FROM keyed
                    GROUP BY {MATCH_KEY}
                )
                SELECT k.{MATCH_KEY}, {wld}, {", ".join(f"k.{c}" for c in part)}, k.geom
                FROM merged k
                LEFT JOIN wld w ON k.iso3 = w.iso3
                ORDER BY k.{MATCH_KEY}
            ) TO '{PARENT}' {PARQUET_OPTS}
        """,
            {"keys": [k.upper() for k in keys]},
        )


def stage(conn: duckdb.DuckDBPyConnection, key: str, meta: tuple, dest: Path) -> None:
    """Write key's layer with adm{n}_id codes, src_* metadata and every level's columns.

    Levels past the source's depth stay null so schema_fill copies the deepest down.
    """
    path = catalog_path("extended", key)
    src_date = meta[[c for c, _ in _META].index("src_date")]
    stamp = (
        conn.execute(f"SELECT max(valid_from) FROM read_parquet('{path}')").fetchall()[
            0
        ][0]
        or src_date
    )
    root = key.upper() if stamp is None else f"{key.upper()}-{stamp:%Y%m%d}"
    have = {r[0] for r in conn.execute(f"DESCRIBE FROM '{path}'").fetchall()}
    cols = [
        _col(c, t, have)
        for c, t in staged_columns()
        if c not in (MATCH_KEY, "adm0_id", *dict(_META)) and _src(c) in have
    ]
    seed = dest.with_name(f"{key}_seed.parquet")
    conn.execute(
        f"""--sql
        COPY (
            SELECT ? AS {MATCH_KEY}, {", ".join(cols)},
                   {", ".join(f"?::{t} AS {c}" for c, t in _META)}
            FROM read_parquet('{path}')
        ) TO '{seed}' {PARQUET_OPTS}
    """,
        [key.upper(), *meta],
    )
    coded = dest.with_name(f"{key}_coded.parquet")
    code_create(
        seed,
        coded,
        dest.with_name(f"{key}_code_issues.parquet"),
        root_code=root,
        delimiter="-",
        min_width="auto",
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
    )
    seed.unlink()
    got = {r[0] for r in conn.execute(f"DESCRIBE FROM '{coded}'").fetchall()}
    padded = ", ".join(
        f'"{c}"' if c in got else f'NULL::{t} AS "{c}"' for c, t in staged_columns()
    )
    conn.execute(f"COPY (SELECT {padded} FROM '{coded}') TO '{dest}' {PARQUET_OPTS}")
    coded.unlink()


def _is_id_slot(name: str) -> bool:
    """adm{n}_id goes before adm{n}_name at every level."""
    return name.endswith("_name")


def _src(col: str) -> str:
    """Source column of `col`: adm{n}_id is seeded from adm{n}_pcode."""
    return col.replace("_id", "_pcode") if col.endswith("_id") else col


def _col(col: str, typ: str, have: set[str]) -> str:
    """Cast `col`; a null adm{n}_name takes the first Latin-script name1..3."""
    value = f'"{_src(col)}"'
    if re.fullmatch(r"adm\d_name", col):
        alts = [f"{col}{i}" for i in (1, 2, 3) if f"{col}{i}" in have]
        latin = (
            f"""CASE WHEN regexp_full_match("{a}", '{LATIN}') THEN "{a}" END"""
            for a in alts
        )
        value = f"coalesce({', '.join((value, *latin))})"
    return f'CAST({value} AS {typ}) AS "{col}"'
