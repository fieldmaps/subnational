"""Sync the catalog, refresh catalog/cod-ab/, and index every source."""

from app._02_publish.utils import sync_catalog
from app.utils import get_conn

from ._01a_hdx import load_hdx
from .sources import build_sources_table


def main() -> None:
    """Pull the published catalog, back up cod-ab, then write the sources table."""
    sync_catalog()
    conn = get_conn()
    load_hdx(conn)
    build_sources_table(conn)
    conn.close()


if __name__ == "__main__":
    main()
