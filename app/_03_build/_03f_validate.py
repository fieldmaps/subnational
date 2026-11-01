"""Scan each adm{n}_polygons table for gap/overlap coverage defects."""

from logging import getLogger

import duckdb
from topo_tools.api import topo_detect

from app.config import PARQUET_OPTS

from ._03b_clip import CLIP_DIR

logger = getLogger(__name__)


def validate(conn: duckdb.DuckDBPyConnection, levels: list[int]) -> None:
    """Run topo-detect against every adm{n}_polygons table, non-blocking."""
    for lvl in levels:
        table = f"adm{lvl}_polygons"
        input_path = CLIP_DIR / f"{table}.parquet"
        issues_path = CLIP_DIR / f"{table}_issues.parquet"
        conn.execute(f"COPY {table} TO '{input_path}' {PARQUET_OPTS}")

        topo_detect(input_path=input_path, output_path=issues_path)

        count = conn.execute(
            f"SELECT COUNT(*) FROM read_parquet('{issues_path}')"
        ).fetchall()[0][0]
        if count:
            logger.warning(
                "%s: %d topology issue(s), see %s", table, count, issues_path
            )
