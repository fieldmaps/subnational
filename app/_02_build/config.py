"""Configuration constants for the build stage."""

from app.config import TMP_DIR

BUILD_DIR = TMP_DIR / "build"
# Parallel per-key jobs x topo-tools threads each: about half the cores.
WORKERS = 2
THREADS = 2

NAME_FIELD = "adm{n}_name"
CODE_FIELD = "adm{n}_id"
# Input/overlay match column; upper-cased key so multi-extent keys (GEO_1) match.
MATCH_KEY = "match_key"
# Input column <- adm0_bounds column on ADM0 parts that no input covers.
ADM0_FILL = {
    "adm0_id": "adm0_id",
    "adm0_pcode": "adm0_src",
    "adm0_name": "adm0_name",
    "adm0_name1": "adm0_name1",
    "adm0_name2": "adm0_name2",
    "iso2": "iso_2",
    "iso3": "iso_3",
}
# World-view columns from adm0_wld that edge_mosaic copies onto every polygon.
WLD_COLS = (
    "iso_cd",
    "iso_2",
    "iso_3",
    "iso_3_grp",
    "region3_cd",
    "region3_nm",
    "region2_cd",
    "region2_nm",
    "region1_cd",
    "region1_nm",
    "status_cd",
    "status_nm",
    "wld_date",
    "wld_update",
    "wld_view",
    "wld_notes",
)
