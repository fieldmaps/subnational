"""Clip per-iso3 inputs to the ADM0 boundary, fill down, and package every level."""

from pathlib import Path
from shutil import rmtree

import duckdb
from topo_tools.api import edge_mosaic, package, schema_fill

from app.config import PARQUET_OPTS, TMP_DIR

from ._03a_inputs import input_paths, stage_extended

CLIP_DIR = TMP_DIR / "build" / "clip"
NAME_FIELD = "adm{n}_name"
CODE_FIELD = "adm{n}_id"


def clip_and_package(conn: duckdb.DuckDBPyConnection) -> list[int]:
    """Build adm{n}_{polygons,lines,points} for n >= 1; return the levels built."""
    rmtree(CLIP_DIR, ignore_errors=True)
    CLIP_DIR.mkdir(parents=True)
    parent_path = CLIP_DIR / "parent.parquet"
    conn.execute(f"""--sql
        COPY (SELECT iso3, geom FROM adm0_bounds) TO '{parent_path}' {PARQUET_OPTS}
    """)

    clipped_path = CLIP_DIR / "clipped.parquet"
    edge_mosaic(
        input_paths=stage_extended(conn),
        overlay_path=parent_path,
        output_path=clipped_path,
        issues_path=CLIP_DIR / "clipped_issues.parquet",
        original_paths=input_paths("original"),
        match_column="iso3",
        merge=True,
        overlay_include=["iso3"],
        input_exclude=["iso3"],
        threads=4,
        tmp_dir=CLIP_DIR,
    )

    filled_path = CLIP_DIR / "filled.parquet"
    schema_fill(
        input_path=_backfill_adm0_identity(conn, clipped_path),
        output_path=filled_path,
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
    )
    # package_points rejects schema_fill's adm_lvl column, so drop it first.
    package_input = CLIP_DIR / "package_input.parquet"
    conn.execute(f"""--sql
        COPY (SELECT * EXCLUDE (adm_lvl) FROM read_parquet('{filled_path}'))
        TO '{package_input}' {PARQUET_OPTS}
    """)
    package(
        package_input,
        CLIP_DIR / "{x}.parquet",
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
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
            SELECT * EXCLUDE (adm_lvl) RENAME (geometry AS geom)
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


def _backfill_adm0_identity(
    conn: duckdb.DuckDBPyConnection, clipped_path: Path
) -> Path:
    """Backfill adm0_id/_src/_name* from adm0_wld for gap-filled territories only."""
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE src_clipped AS
        SELECT * FROM read_parquet('{clipped_path}')
    """)
    conn.execute("""--sql
        UPDATE src_clipped SET
            adm0_id = w.adm0_id, adm0_src = w.adm0_src, adm0_name = w.adm0_name,
            adm0_name1 = w.adm0_name1, adm0_name2 = w.adm0_name2
        FROM adm0_wld w
        WHERE src_clipped.iso3 = w.iso_3 AND src_clipped.adm0_id IS NULL
    """)
    path = clipped_path.with_name("clipped_backfilled.parquet")
    conn.execute(f"COPY src_clipped TO '{path}' {PARQUET_OPTS}")
    return path
