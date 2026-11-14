"""Clip per-iso3 inputs to the ADM0 boundary, fill down, and package every level."""

from logging import getLogger
from pathlib import Path
from shutil import rmtree

import duckdb
from topo_tools.api import edge_mosaic, package, schema_fill

from app.config import PARQUET_OPTS, TMP_DIR

from ._02a_inputs import input_paths, stage_extended
from .config import ADM0_FILL, CODE_FIELD, MATCH_KEY, NAME_FIELD, WLD_COLS

logger = getLogger(__name__)

CLIP_DIR = TMP_DIR / "build" / "clip"


def clip_and_package(conn: duckdb.DuckDBPyConnection) -> list[int]:
    """Build adm{n}_{polygons,lines,points} for n >= 1; return the levels built."""
    rmtree(CLIP_DIR, ignore_errors=True)
    CLIP_DIR.mkdir(parents=True)
    parent_path = CLIP_DIR / "parent.parquet"
    conn.execute(f"COPY adm0_bounds TO '{parent_path}' {PARQUET_OPTS}")

    clipped_path = CLIP_DIR / "clipped.parquet"
    issues_path = CLIP_DIR / "clipped_issues.parquet"
    edge_mosaic(
        input_paths=stage_extended(conn),
        overlay_path=parent_path,
        output_path=clipped_path,
        issues_path=issues_path,
        original_paths=input_paths("original"),
        match_column=MATCH_KEY,
        merge=True,
        overlay_include=[MATCH_KEY, *WLD_COLS],
        input_exclude=[MATCH_KEY],
        fill=ADM0_FILL,
        threads=4,
        tmp_dir=CLIP_DIR,
        # The global coverage clean exits the process on a 16 GB machine.
        clean=False,
    )
    _log_issues(conn, issues_path)

    filled_path = CLIP_DIR / "filled.parquet"
    schema_fill(
        input_path=clipped_path,
        output_path=filled_path,
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
    )
    # Clip seams are accepted; validation errors are reported, not raised.
    package(
        filled_path,
        CLIP_DIR / "{x}.parquet",
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
        min_level=1,
        clean=False,
        block=False,
        threads=4,
        tmp_dir=CLIP_DIR,
    )

    levels = sorted(
        int(p.stem.removeprefix("admin")) for p in CLIP_DIR.glob("admin[1-9].parquet")
    )
    for lvl in levels:
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE adm{lvl}_polygons AS
            SELECT * RENAME (geometry AS geom)
            FROM read_parquet('{CLIP_DIR / f"admin{lvl}.parquet"}')
        """)
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE adm{lvl}_points AS
            SELECT * RENAME (geometry AS geom)
            FROM read_parquet('{CLIP_DIR / "points.parquet"}')
            WHERE adm_lvl = {lvl}
        """)
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE adm{lvl}_lines AS
            SELECT * RENAME (geometry AS geom)
            FROM read_parquet('{CLIP_DIR / "lines.parquet"}')
            WHERE adm_lvl <= {lvl}
        """)
    return levels


def _log_issues(conn: duckdb.DuckDBPyConnection, issues_path: Path) -> None:
    """Warn with edge_mosaic's issue counts per kind, non-blocking."""
    if not issues_path.exists():
        return
    for kind, count in conn.execute(
        f"SELECT kind, count(*) FROM read_parquet('{issues_path}') GROUP BY ALL"
    ).fetchall():
        logger.warning("edge_mosaic: %d %s issue(s), see %s", count, kind, issues_path)
