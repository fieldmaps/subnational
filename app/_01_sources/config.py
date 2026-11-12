"""Configuration constants for the sources stage."""

from app.config import TMP_DIR

DOWNLOAD_DIR = TMP_DIR / "sources"

SRC = "cod-ab"
COD_AB_DATA = "https://data.source.coop/hdx/cod-ab"
COD_AB_URL = "https://source.coop/hdx/cod-ab"
COD_AB_META_API = "https://data.humdata.org/api/3/action/package_show?id=cod-ab-global"
COD_AB_META_CSV = "global_admin_boundaries_metadata_latest.csv"
COD_AB_SRC_URL = "https://data.humdata.org/dataset/cod-ab-global"

HTTP_CONNECT_TIMEOUT = 30
DOWNLOAD_CHUNK_SIZE = 4 * 1024 * 1024
