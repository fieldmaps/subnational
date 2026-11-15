"""Register catalog/global/ collections with portolan."""

from collections import Counter
from itertools import product

import app.config
from app._01_sources.schema import SOURCES_SQL
from app.config import CATALOG_DIR, GEOMS, MAX_LVL
from app.publish.config import HOST, INTERNATIONAL_URL
from app.publish.utils import (
    ensure_catalog,
    finalize,
    license_fields,
    portolan,
    tile_collection,
    write_metadata,
)
from app.utils import get_conn, global_path

from .config import GLOBAL_LICENSE

_VIEW = (
    "Humanitarian world view, which groups disputed and autonomous areas with a "
    "neighbouring area, clipped to the OSM-based admin 0 polygons of "
    f"{INTERNATIONAL_URL}."
)
_ADM0 = (
    "Carries no country-level columns, coastlines or international borders: use "
    f"the admin 0 polygons, points and lines of {INTERNATIONAL_URL} for those."
)
_DESCRIPTIONS = {
    "polygons": "Admin level {n} areas, dissolved from the finest source level, "
    "with every admin column for levels 0 to {n} and source metadata.",
    "points": "One label point per admin level {n} area, with its id, names and "
    f"pcode. {_ADM0}",
    "lines": "Boundary lines for admin levels 1 to {n}, each side labelled with "
    f"the units at the line's adm_lvl. {_ADM0}",
}


def main() -> None:
    """Write metadata.yaml per global collection, add, check, and push with --push."""
    ensure_catalog()
    adm1 = global_path(1, "polygons")
    if not adm1.exists():
        msg = f"{adm1} is missing: run the build step first"
        raise FileNotFoundError(msg)
    conn = get_conn()
    stamp = conn.execute(f"SELECT max(wld_date) FROM '{adm1}'").fetchall()[0][0]
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
    for lvl, geom in product(range(1, MAX_LVL + 1), GEOMS):
        folder = f"global/adm{lvl}-{geom}"
        write_metadata(
            CATALOG_DIR / folder,
            title=f"ADM{lvl} {geom} (humanitarian view, ODbL)",
            description=f"{_DESCRIPTIONS[geom].format(n=lvl)} {_VIEW}",
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
