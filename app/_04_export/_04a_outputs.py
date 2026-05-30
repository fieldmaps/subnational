"""Copy build.duckdb's adm{1..4} tables out as GeoParquet files."""

import logging

import duckdb

from app.config import BUILD_DB, EDGE_MATCHED_DIR, GEOMS, PARQUET_OPTS, WLD
from app.utils import get_conn

logger = logging.getLogger(__name__)


def main() -> None:
    """Write outputs/edge-matched/{WLD}/adm{1..4}_{geom}.parquet for every table."""
    conn = get_conn(BUILD_DB, read_only=True)
    try:
        out_dir = EDGE_MATCHED_DIR / WLD
        out_dir.mkdir(parents=True, exist_ok=True)
        for lvl in range(1, 5):
            for geom in GEOMS:
                table = f"adm{lvl}_{geom}"
                dest = out_dir / f"{table}.parquet"
                try:
                    _export_table(conn, table, dest)
                except duckdb.Error as e:
                    logger.warning("skip %s: %s", table, e)
    finally:
        conn.close()


def _export_table(conn: duckdb.DuckDBPyConnection, table: str, dest: object) -> None:
    """Write one table to GeoParquet, ordered by whichever adm*_id columns it has."""
    cols = [row[0] for row in conn.execute(f"DESCRIBE {table}").fetchall()]
    ids = [f"adm{i}_id" for i in range(5) if f"adm{i}_id" in cols]
    order = f" ORDER BY {', '.join(ids)}" if ids else ""
    conn.execute(f"COPY (SELECT * FROM {table}{order}) TO '{dest}' {PARQUET_OPTS}")
