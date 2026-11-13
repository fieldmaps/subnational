"""Stage the published per-iso3 inputs and build the ADM0 clip boundary."""

import re

import duckdb
from topo_tools.api import code_create, topo_clean

from app._01_sources.schema import SOURCES_SQL, columns
from app._01_sources.utils import catalog_path
from app.config import MAX_LVL, PARQUET_OPTS, TMP_DIR

from .config import (
    ADM0_BASE,
    ADM0_DISAGGREGATED,
    ADM0_HUMANITARIAN,
    ADM0_LOCAL,
    CLIP_PARTS,
    CODE_FIELD,
    MATCH_KEY,
    NAME_FIELD,
    WLD_COLS,
)

STAGE_DIR = TMP_DIR / "build" / "inputs"
_LATIN = r"[\p{Latin}\p{Common}\p{Inherited}]+"
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
    """Return the published {tier} parquet paths, sorted by key."""
    return [str(catalog_path(tier, key)) for key in _keys(tier)]


def stage_extended(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Add fieldmaps adm{n}_id codes and src_* metadata to each published layer.

    MATCH_KEY is the upper-cased key so multi-extent keys (e.g. GEO_1) match.
    """
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for key in _keys("extended"):
        row = conn.execute(
            f"SELECT {', '.join(_META)} FROM ({SOURCES_SQL}) "
            "WHERE tier = 'extended' AND key = ?",
            [key],
        ).fetchall()[0]
        meta = dict(zip(_META, row, strict=True))
        path = catalog_path("extended", key)
        stamp = (
            conn.execute(
                f"SELECT max(CAST(valid_on AS DATE)) FROM read_parquet('{path}')"
            ).fetchall()[0][0]
            or meta["src_date"]
        )
        root = key.upper() if stamp is None else f"{key.upper()}-{stamp:%Y%m%d}"
        have = {r[0] for r in conn.execute(f"DESCRIBE FROM '{path}'").fetchall()}
        cols = [
            _col(c, t, have)
            for name, t in columns(MAX_LVL)
            for c in ((f"{name[:4]}_id", name) if _is_id_slot(name) else (name,))
            if _src(c) in have
        ]
        seed = STAGE_DIR / f"{key}_seed.parquet"
        conn.execute(
            f"""--sql
            COPY (
                SELECT ? AS {MATCH_KEY}, {", ".join(cols)},
                       {", ".join(f"?::{_type(c)} AS {c}" for c in _META)}
                FROM read_parquet('{path}')
            ) TO '{seed}' {PARQUET_OPTS}
        """,
            [key.upper(), *row],
        )
        coded = STAGE_DIR / f"{key}_coded.parquet"
        code_create(
            seed,
            coded,
            STAGE_DIR / f"{key}_issues.parquet",
            root_code=root,
            delimiter="-",
            min_width="auto",
            name_field=NAME_FIELD,
            code_field=CODE_FIELD,
        )
        dest = STAGE_DIR / f"{key}.parquet"
        # edge_mosaic raises unless every input is a clean coverage.
        topo_clean(coded, dest, STAGE_DIR / f"{key}_clean_issues.parquet", threads=4)
        seed.unlink()
        coded.unlink()
        paths.append(str(dest))
    return paths


def _is_id_slot(name: str) -> bool:
    """adm{n}_id goes before adm{n}_name for every level below adm0."""
    return name.endswith("_name") and name != "adm0_name"


def _src(col: str) -> str:
    """Source column of `col`: adm{n}_id is seeded from adm{n}_pcode."""
    return col.replace("_id", "_pcode") if col.endswith("_id") else col


def _col(col: str, typ: str, have: set[str]) -> str:
    """Cast `col`; a null adm{n}_name takes the first Latin-script name1..3."""
    value = f'"{_src(col)}"'
    if re.fullmatch(r"adm\d_name", col):
        alts = [f"{col}{i}" for i in (1, 2, 3) if f"{col}{i}" in have]
        latin = (
            f"""CASE WHEN regexp_full_match("{a}", '{_LATIN}') THEN "{a}" END"""
            for a in alts
        )
        value = f"coalesce({', '.join((value, *latin))})"
    return f'CAST({value} AS {typ}) AS "{col}"'


def _type(col: str) -> str:
    return {"src_lvl": "INTEGER", "src_date": "DATE", "src_update": "DATE"}.get(
        col, "VARCHAR"
    )


def _keys(tier: str) -> list[str]:
    """Return the published keys of one tier, sorted."""
    with duckdb.connect() as conn:
        rows = conn.execute(
            f"SELECT key FROM ({SOURCES_SQL}) WHERE tier = ? ORDER BY key", [tier]
        ).fetchall()
    return [key for (key,) in rows]


def load_adm0(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm0_clip, adm0_wld (one row per iso_3), and adm0_bounds (per match key).

    adm0_bounds carries the parent's world-view columns that edge_mosaic copies over.
    """
    conn.execute(f"CREATE OR REPLACE TABLE adm0_clip AS {adm0_clip_sql()}")
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE adm0_wld AS
        SELECT * EXCLUDE (geometry) FROM read_parquet('{adm0_path(ADM0_HUMANITARIAN)}')
        QUALIFY row_number() OVER (PARTITION BY iso_3 ORDER BY adm0_id) = 1
    """)
    wld = ", ".join(f"w.{c}" for c in WLD_COLS)
    keys = [k.upper() for k in _keys("extended")]
    # A part keeps its own key when an input has it, else merges under its iso_3.
    conn.execute(
        f"""--sql
        CREATE OR REPLACE TABLE adm0_bounds AS
        WITH keyed AS (
            SELECT CASE WHEN list_contains($keys, adm0_src) THEN adm0_src
                        WHEN list_contains($keys, iso_3) THEN iso_3
                        ELSE adm0_src END AS {MATCH_KEY},
                   iso_3, geometry
            FROM adm0_clip
        ), merged AS (
            SELECT {MATCH_KEY}, any_value(iso_3) AS iso_3,
                   ST_Union_Agg(geometry)::GEOMETRY AS geom
            FROM keyed
            GROUP BY {MATCH_KEY}
        )
        SELECT k.{MATCH_KEY}, {wld}, k.geom
        FROM merged k
        LEFT JOIN adm0_wld w ON k.iso_3 = w.iso_3
    """,
        {"keys": keys},
    )


def adm0_clip_sql() -> str:
    """Return the humanitarian ADM0 with each CLIP_PARTS parent split into parts."""
    parts = ", ".join(f"('{s}', '{d}')" for s, d in CLIP_PARTS.items())
    return f"""--sql
        WITH p(src, dst) AS (VALUES {parts})
        SELECT * FROM read_parquet('{adm0_path(ADM0_HUMANITARIAN)}')
        WHERE adm0_src NOT IN (SELECT split_part(dst, '_', 1) FROM p)
        UNION ALL BY NAME
        SELECT d.* REPLACE (p.dst AS adm0_src, split_part(p.dst, '_', 1) AS iso_3)
        FROM read_parquet('{adm0_path(ADM0_DISAGGREGATED)}') d
        JOIN p ON d.adm0_src = p.src
    """


def adm0_path(rel: str) -> str:
    """Return the local international catalog file if present, else its URL."""
    local = ADM0_LOCAL / rel
    return str(local) if local.exists() else f"{ADM0_BASE}/{rel}"
