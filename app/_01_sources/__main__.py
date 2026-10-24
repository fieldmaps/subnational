"""Write catalog/{extended,original}/ and the per-iso3 sources table."""

import pandas as pd

from app.config import SOURCES_TABLE
from app.utils import get_conn

from ._01a_hdx import load_hdx
from ._01b_legacy import load_legacy
from .config import COD_LIST_URL, GB_LIST_URL


def main() -> None:
    """Select source.coop first, then legacy COD, then legacy geoBoundaries."""
    conn = get_conn()
    rows = load_hdx(conn)
    for list_url, src in ((COD_LIST_URL, "cod"), (GB_LIST_URL, "geoboundaries")):
        covered = {r["iso3"].split("_")[0] for r in rows}
        rows += load_legacy(conn, list_url, src, covered)
    conn.register("sources", pd.DataFrame(rows))
    SOURCES_TABLE.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(f"COPY (SELECT * FROM sources ORDER BY key) TO '{SOURCES_TABLE}'")
    conn.close()


if __name__ == "__main__":
    main()
