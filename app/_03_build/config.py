"""Configuration constants for the build stage."""

from app.config import PKG_DIR

ADM0_BASE = "https://data.source.coop/fieldmaps/international"
ADM0_LOCAL = PKG_DIR.parent.parent / "international" / "catalog"
ADM0_HUMANITARIAN = "odbl/humanitarian/adm0-polygons/adm0_polygons.parquet"
ADM0_DISAGGREGATED = "odbl/disaggregated/adm0-polygons/adm0_polygons.parquet"

CLIP_DROP = ("GEO", "SRB", "XJK")
CLIP_ADD = ("GEO_1", "GEO_2", "GEO_3", "SRB_1", "SRB_2", "XKX", "XAK", "XSS", "XJK")

NAME_FIELD = "adm{n}_name"
CODE_FIELD = "adm{n}_id"
# Input/overlay match column; upper-cased key so multi-extent keys (GEO_1) match.
MATCH_KEY = "match_key"
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
