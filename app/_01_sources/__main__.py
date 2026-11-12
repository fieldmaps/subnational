"""Refresh sources/cod-ab/ and index every source."""

from app.utils import get_conn

from ._01a_hdx import load_hdx
from .sources import build_sources_table


def main() -> None:
    """Back up cod-ab, then write the sources table."""
    conn = get_conn()
    load_hdx(conn)
    build_sources_table(conn)
    conn.close()


if __name__ == "__main__":
    main()
