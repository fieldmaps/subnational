"""Configuration constants for the sources stage."""

from app.config import PKG_DIR, TMP_DIR

DOWNLOAD_DIR = TMP_DIR / "sources"

SRC = "cod-ab"
SC_BASE = "https://data.source.coop/hdx/cod-ab"
SC_LOCAL = (
    PKG_DIR.parent.parent.parent / "OCHA-DAP" / "hdx-scraper-cod-ab-global" / "portolan"
)
SC_URL = "https://source.coop/hdx/cod-ab"
HDX_PACKAGE = "https://data.humdata.org/api/3/action/package_show?id=cod-ab-global"
HDX_META_NAME = "global_admin_boundaries_metadata_latest.csv"
HDX_SRC_URL = "https://data.humdata.org/dataset/cod-ab-global"

HTTP_CONNECT_TIMEOUT = 30
DOWNLOAD_CHUNK_SIZE = 4 * 1024 * 1024
