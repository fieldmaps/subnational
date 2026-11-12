"""Register catalog/global/ collections with portolan."""

from collections import Counter

import app.config
from app._01_sources.schema import SOURCES_SQL
from app.config import BUILD_DB, CATALOG_DIR
from app.publish.config import HOST, INTERNATIONAL_URL
from app.publish.utils import (
    ensure_catalog,
    finalize,
    license_fields,
    portolan,
    tile_collection,
    write_metadata,
)
from app.utils import get_conn

from .config import GLOBAL_LICENSE
from .utils import build_levels

_VIEW = (
    "Humanitarian world view, which groups disputed and autonomous areas with a "
    "neighbouring area, clipped to the OSM-based admin 0 polygons of "
    f"{INTERNATIONAL_URL}."
)
_FILES = (
    "admin{n}.parquet: polygons, dissolved from the finest source level; "
    "admin{n}_points.parquet: one label point per polygon; "
    "admin{n}_lines.parquet: boundary lines up to this level "
    "(adm_lvl -1 is the exterior edge)."
)


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
    force = ["--force"] if app.config.FORCE_PMTILES else []
    for lvl in levels:
        folder = f"global/admin{lvl}"
        write_metadata(
            CATALOG_DIR / folder,
            title=f"Admin {lvl}",
            description=f"Admin level {lvl}. {_FILES.format(n=lvl)} {_VIEW}",
            **license_fields(GLOBAL_LICENSE, None),
            providers=[HOST],
            processing_notes=notes,
        )
        tile_collection(CATALOG_DIR / folder, force=app.config.FORCE_PMTILES)
        portolan("add", folder, *when, *force)
    finalize(changed=True)


def _source_notes() -> str:
    """Summarize source and SPDX license counts across the per-iso3 inputs."""
    conn = get_conn()
    rows = conn.execute(
        f"SELECT src, src_lic, src_url FROM ({SOURCES_SQL}) WHERE tier = 'extended'"
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
