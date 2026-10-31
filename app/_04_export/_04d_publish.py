"""Register catalog/global/ collections with portolan."""

from collections import Counter

import app.config
from app._02_publish.config import HOST, INTERNATIONAL_URL
from app._02_publish.utils import (
    ensure_catalog,
    license_fields,
    portolan,
    write_metadata,
)
from app.config import BUILD_DB, CATALOG_DIR, SOURCES_TABLE
from app.utils import get_conn

from .config import GLOBAL_LICENSE
from .utils import build_levels

_VIEW = (
    "Humanitarian world view, which groups disputed and autonomous areas with a "
    "neighbouring area, clipped to the OSM-based admin 0 polygons of "
    f"{INTERNATIONAL_URL}."
)
_GEOM_TEXT = {
    "polygons": "polygons, dissolved from the finest source level",
    "lines": "boundary lines up to this level (adm_lvl -1 is the exterior edge)",
    "points": "one interior point per polygon",
}


def main() -> None:
    """Write metadata.yaml per global collection, add, check, and push with --push."""
    ensure_catalog()
    conn = get_conn(BUILD_DB, read_only=True)
    levels = build_levels(conn)
    stamp = conn.execute("SELECT max(wld_date) FROM adm0_wld").fetchall()[0][0]
    conn.close()
    notes = _source_notes()
    write_metadata(
        CATALOG_DIR / "global",
        title="Global edge-matched layers",
        description=_VIEW,
        **license_fields(GLOBAL_LICENSE, None),
        providers=[HOST],
        processing_notes=notes,
    )
    when = ["--datetime", str(stamp)[:10]] if stamp else []
    for lvl in levels:
        for geom, text in _GEOM_TEXT.items():
            folder = f"global/adm{lvl}-{geom}"
            write_metadata(
                CATALOG_DIR / folder,
                title=f"Admin {lvl} {geom}",
                description=f"Admin level {lvl} {text}. {_VIEW}",
                **license_fields(GLOBAL_LICENSE, None),
                providers=[HOST],
                processing_notes=notes,
            )
            portolan("add", folder, "--pmtiles", *when)
    portolan("metadata", "validate")
    portolan("readme")
    portolan("check", "--data-scope", "local")
    if app.config.PUSH:
        portolan("push", "--dry-run")
        portolan("push")


def _source_notes() -> str:
    """Summarize source and SPDX license counts across the per-iso3 inputs."""
    conn = get_conn()
    rows = conn.execute(
        f"SELECT src, src_lic, src_url FROM read_parquet('{SOURCES_TABLE}') "
        "WHERE selected AND tier = 'extended'"
    ).fetchall()
    conn.close()
    srcs = Counter(src for src, _, _ in rows)
    lics = Counter(license_fields(lic, url)["license"] for _, lic, url in rows)
    src_text = ", ".join(f"{n} from {s}" for s, n in srcs.most_common())
    lic_text = "; ".join(f"{lic} ({n})" for lic, n in lics.most_common())
    return (
        f"Built from the per-iso3 extended layers ({src_text}), edge-matched with "
        f"topo-tools. Source licenses: {lic_text}."
    )
