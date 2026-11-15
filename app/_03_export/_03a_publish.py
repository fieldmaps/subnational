"""Register the catalog/iso3/ and catalog/global/ collections with portolan."""

from collections import Counter
from itertools import product

import app.config
from app._01_sources._01b_publish import _license_name
from app._01_sources.schema import SOURCES_SQL
from app._02_build.config import ISO3
from app.adm0 import ADM0_HUMANITARIAN, adm0_path
from app.config import CATALOG_DIR, GEOMS, MAX_LVL
from app.publish.config import HOST, INTERNATIONAL_URL, SRC_NOTICES
from app.publish.utils import (
    ensure_catalog,
    finalize,
    license_fields,
    portolan,
    stale_collections,
    tile_collection,
    write_metadata,
)
from app.utils import get_conn, global_path

from .config import GLOBAL_LICENSE

# FieldMaps produces the edge-matched layers from the source/ layers.
_PRODUCER = {**HOST, "roles": ["producer", *HOST["roles"]]}
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
    f"the units at the line's level. {_ADM0}",
}


def main() -> None:
    """Write metadata.yaml per iso3 and global collection, add, check, push."""
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
        providers=[_PRODUCER],
        processing_notes=notes,
    )
    when = ["--datetime", str(stamp)[:10]] if stamp else []
    _publish_codes(when, notes)
    force = ["--force"] if app.config.FORCE_PMTILES else []
    for lvl, geom in product(range(1, MAX_LVL + 1), GEOMS):
        folder = f"global/adm{lvl}-{geom}"
        write_metadata(
            CATALOG_DIR / folder,
            title=f"ADM{lvl} {geom} (humanitarian view, ODbL)",
            description=f"{_DESCRIPTIONS[geom].format(n=lvl)} {_VIEW}",
            **license_fields(GLOBAL_LICENSE, None),
            providers=[_PRODUCER],
            processing_notes=notes,
        )
        tile_collection(CATALOG_DIR / folder, force=app.config.FORCE_PMTILES)
        portolan("add", folder, *when, *force)
    finalize(changed=True)


def _publish_codes(when: list[str], notes: str) -> None:
    """Write metadata per iso3 collection; tile and add the changed ones."""
    write_metadata(
        CATALOG_DIR / "iso3",
        title="Edge-matched layers by ISO3",
        description=f"The global layers cut by world-view iso3, one collection each. "
        f"{_VIEW}",
        **license_fields(GLOBAL_LICENSE, None),
    )
    conn = get_conn()
    names = dict(
        conn.execute(
            f"SELECT lower({ISO3}), any_value(adm0_name1) "
            f"FROM read_parquet('{adm0_path(ADM0_HUMANITARIAN)}') GROUP BY 1"
        ).fetchall()
    )
    stale = stale_collections()
    for folder in sorted((CATALOG_DIR / "iso3").glob("*/")):
        code = folder.name
        srcs = conn.execute(
            f"SELECT DISTINCT src_grp, src_name, src_lic, src_url "
            f"FROM '{folder}/adm1_polygons.parquet' WHERE src_name IS NOT NULL "
            "ORDER BY ALL"
        ).fetchall()
        changed = write_metadata(
            folder,
            title=f"{names[code]} ({code.upper()}) edge-matched layers",
            description=_code_description(srcs),
            **license_fields(GLOBAL_LICENSE, None),
            providers=[_PRODUCER],
            processing_notes=notes,
            keywords=[code.upper(), *dict.fromkeys(g for g, *_ in srcs)],
        )
        if (
            app.config.FORCE_PMTILES
            or changed
            or f"iso3/{code}" in stale
            or not (folder / "versions.json").exists()
        ):
            tile_collection(folder, force=app.config.FORCE_PMTILES)
            portolan("add", f"iso3/{code}", *when, "--force")
    conn.close()


def _code_description(srcs: list[tuple]) -> str:
    """Describe one iso3 collection's layers, sources and required notices."""
    used = "; ".join(
        f"{name} ({_license_name(lic, url)}, {url})" for _, name, lic, url in srcs
    )
    text = (
        f"Admin levels 1 to {MAX_LVL}, each with polygons, points and lines. "
        + (f"Sources: {used}. " if srcs else "")
        + "Parts no source covers repeat their admin 0 area at every level. "
    )
    grps = {g.lower() for g, *_ in srcs if g}
    notices = "".join(f" {SRC_NOTICES[g]}" for g in sorted(grps & set(SRC_NOTICES)))
    return f"{text}{_ADM0} {_VIEW}{notices}"


def _source_notes() -> str:
    """Summarize source and SPDX license counts across the source/ inputs."""
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
        f"Built from the source/ extended layers ({src_text}), edge-matched with "
        f"topo-tools. Source licenses: {lic_text}."
    )
