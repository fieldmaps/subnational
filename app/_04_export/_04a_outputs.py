"""Copy build.duckdb's adm{n}_{geom} tables out as GeoParquet collections."""

import duckdb

from app.config import BUILD_DB, GEOMS, PARQUET_OPTS
from app.utils import get_conn

from .utils import build_levels, global_path


def main() -> None:
    """Write catalog/global/adm{n}-{geom}/adm{n}_{geom}.parquet for every table."""
    conn = get_conn(BUILD_DB, read_only=True)
    try:
        for lvl in build_levels(conn):
            for geom in GEOMS:
                _export_table(conn, f"adm{lvl}_{geom}", global_path(lvl, geom))
    finally:
        conn.close()


def _export_table(conn: duckdb.DuckDBPyConnection, table: str, dest: object) -> None:
    """Write one table to GeoParquet, ordered by whichever id columns it has."""
    cols = [row[0] for row in conn.execute(f"DESCRIBE {table}").fetchall()]
    keys = [f"adm{i}_id" for i in range(10)] + ["code", "a_code"]
    ids = [c for c in keys if c in cols]
    order = f" ORDER BY {', '.join(ids)}" if ids else ""
    exclude = "iso3, geom" if "iso3" in cols else "geom"
    conn.execute(f"""--sql
        COPY (SELECT * EXCLUDE ({exclude}), geom AS geometry FROM {table}{order})
        TO '{dest}' {PARQUET_OPTS}
    """)
