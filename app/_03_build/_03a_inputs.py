"""Stage the selected per-iso3 inputs and build the ADM0 clip boundary."""

import duckdb
from topo_tools.api import code_create, topo_clean

from app._01_sources.schema import columns
from app._01_sources.utils import catalog_path
from app.config import MAX_LVL, PARQUET_OPTS, SOURCES_TABLE, TMP_DIR

from .config import (
    ADM0_BASE,
    ADM0_DISAGGREGATED,
    ADM0_HUMANITARIAN,
    ADM0_LOCAL,
    CLIP_ADD,
    CLIP_DROP,
    CODE_FIELD,
    MATCH_KEY,
    NAME_FIELD,
    WLD_COLS,
)

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
    """Add fieldmaps adm{n}_id codes and src_* metadata to each selected layer.

    MATCH_KEY is the upper-cased key so multi-extent keys (e.g. GEO_1) match.
    """
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for src, key in _selected("extended"):
        row = conn.execute(
            f"SELECT {', '.join(_META)} FROM read_parquet('{SOURCES_TABLE}') "
            "WHERE tier = 'extended' AND src = ? AND key = ?",
            [src, key],
        ).fetchall()[0]
        meta = dict(zip(_META, row, strict=True))
        path = catalog_path(src, "extended", key)
        stamp = (
            conn.execute(
                f"SELECT max(CAST(valid_on AS DATE)) FROM read_parquet('{path}')"
            ).fetchall()[0][0]
            or meta["src_date"]
        )
        root = key.upper() if stamp is None else f"{key.upper()}-{stamp:%Y%m%d}"
        have = {r[0] for r in conn.execute(f"DESCRIBE FROM '{path}'").fetchall()}
        cols = [
            _col(c, t)
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


def _col(col: str, typ: str) -> str:
    return f'CAST("{_src(col)}" AS {typ}) AS "{col}"'


def _type(col: str) -> str:
    return {"src_lvl": "INTEGER", "src_date": "DATE", "src_update": "DATE"}.get(
        col, "VARCHAR"
    )


def _selected(tier: str) -> list[tuple[str, str]]:
    """Return (src, key) of the selected rows of one tier, sorted by key."""
    with duckdb.connect() as conn:
        return conn.execute(
            f"SELECT src, key FROM read_parquet('{SOURCES_TABLE}') "
            "WHERE selected AND tier = ? ORDER BY key",
            [tier],
        ).fetchall()


def load_adm0(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm0_clip, adm0_wld (one row per iso_3), and adm0_bounds (per match key).

    adm0_clip is the humanitarian view with CLIP_DROP swapped for CLIP_ADD;
    adm0_bounds carries the world-view columns that edge_mosaic copies over.
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
    wld = ", ".join(f"w.{c}" for c in WLD_COLS)
    conn.execute(rf"""--sql
        CREATE OR REPLACE TABLE adm0_bounds AS
        WITH keyed AS (
            SELECT adm0_src AS {MATCH_KEY}, ST_Union_Agg(geometry)::GEOMETRY AS geom
            FROM adm0_clip
            GROUP BY adm0_src
            UNION ALL
            SELECT iso_3 AS {MATCH_KEY}, ST_Union_Agg(geometry)::GEOMETRY AS geom
            FROM adm0_clip
            WHERE iso_3 != adm0_src
            GROUP BY iso_3
        )
        SELECT k.{MATCH_KEY}, {wld}, k.geom
        FROM keyed k
        LEFT JOIN adm0_wld w ON regexp_replace(k.{MATCH_KEY}, '_\d+$', '') = w.iso_3
    """)


def adm0_path(rel: str) -> str:
    """Return the local international catalog file if present, else its URL."""
    local = ADM0_LOCAL / rel
    return str(local) if local.exists() else f"{ADM0_BASE}/{rel}"
