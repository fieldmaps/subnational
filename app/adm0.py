"""ADM0 clip layers from the international catalog, shared by sources and build."""

from app.config import PKG_DIR

ADM0_BASE = "https://data.source.coop/fieldmaps/international"
ADM0_LOCAL = PKG_DIR.parent.parent / "international" / "catalog"
ADM0_HUMANITARIAN = "odbl/humanitarian/adm0-polygons/adm0_polygons.parquet"
ADM0_DISAGGREGATED = "odbl/disaggregated/adm0-polygons/adm0_polygons.parquet"

# Disaggregated adm0_src -> clip part replacing its humanitarian parent (prefix).
CLIP_PARTS = {
    "SRB_1": "SRB_1",
    "SRB_2": "SRB_2",
    "XKX": "SRB_3",
    "GEO_1": "GEO_1",
    "GEO_2": "GEO_2",
    "GEO_3": "GEO_3",
    "XJK": "XJK_1",
    "XAK": "XJK_2",
    "XSS": "XJK_3",
}


def adm0_clip_sql() -> str:
    """Return the humanitarian ADM0 with each CLIP_PARTS parent split into parts."""
    parts = ", ".join(f"('{s}', '{d}')" for s, d in CLIP_PARTS.items())
    return f"""--sql
        WITH p(src, dst) AS (VALUES {parts})
        SELECT * FROM read_parquet('{adm0_path(ADM0_HUMANITARIAN)}')
        WHERE adm0_src NOT IN (SELECT split_part(dst, '_', 1) FROM p)
        UNION ALL BY NAME
        SELECT d.* REPLACE (p.dst AS adm0_src, split_part(p.dst, '_', 1) AS iso_3)
        FROM read_parquet('{adm0_path(ADM0_DISAGGREGATED)}') d
        JOIN p ON d.adm0_src = p.src
    """


def adm0_path(rel: str) -> str:
    """Return the local international catalog file if present, else its URL."""
    local = ADM0_LOCAL / rel
    return str(local) if local.exists() else f"{ADM0_BASE}/{rel}"
