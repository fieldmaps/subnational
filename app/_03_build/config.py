"""Configuration constants for the build stage."""

from app.config import PKG_DIR

ADM0_BASE = "https://data.source.coop/fieldmaps/international"
ADM0_LOCAL = PKG_DIR.parent.parent / "international" / "catalog"
ADM0_HUMANITARIAN = "odbl/humanitarian/adm0-polygons/adm0_polygons.parquet"
ADM0_DISAGGREGATED = "odbl/disaggregated/adm0-polygons/adm0_polygons.parquet"

CLIP_DROP = ("GEO", "SRB", "XJK")
CLIP_ADD = ("GEO_1", "GEO_2", "GEO_3", "SRB_1", "SRB_2", "XKX", "XAK", "XSS", "XJK")
