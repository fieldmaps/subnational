"""Download and ingest all source data into tmp/prepare.duckdb."""

import app.config
from app.config import PREPARE_DB
from app.utils import export_debug_tables, get_conn

from ._02a_hdx import load_hdx
from ._02b_fallbacks import load_fallback
from .config import COD_BASE, COD_LIST_URL, GB_BASE, GB_LIST_URL


def main() -> None:
    """Build tmp/prepare.duckdb with admin + metadata tables from all sources."""
    conn = get_conn(PREPARE_DB, reset=True)
    load_hdx(conn)
    load_fallback(conn, COD_LIST_URL, COD_BASE, "cod")
    load_fallback(conn, GB_LIST_URL, GB_BASE, "geoboundaries")
    if app.config.DEBUG:
        export_debug_tables(conn, "prepare")
    conn.close()


if __name__ == "__main__":
    main()
