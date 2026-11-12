"""Pull the catalog, refresh cod-ab in catalog/iso3/, and publish what changed."""

from app.publish.utils import sync_catalog
from app.utils import get_conn

from ._01a_cod_ab import load_cod_ab
from ._01b_publish import publish


def main() -> None:
    """Pull catalog/, refresh cod-ab collections, then add and push changed ones."""
    sync_catalog()
    conn = get_conn()
    load_cod_ab(conn)
    conn.close()
    publish()


if __name__ == "__main__":
    main()
