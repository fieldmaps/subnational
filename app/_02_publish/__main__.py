"""Register catalog/{src}/{base} collections with portolan."""

from logging import getLogger

import duckdb

import app.config
from app._01_sources.utils import catalog_path
from app.config import CATALOG_DIR, SOURCES_TABLE
from app.utils import get_conn

from . import fieldmaps_publish
from .config import HOST, SRC_DESCRIPTIONS, SRC_NAMES, TIERS
from .utils import (
    ensure_catalog,
    license_fields,
    portolan,
    stale_collections,
    tile_collection,
    write_metadata,
)

logger = getLogger(__name__)


def main() -> None:
    """Write metadata.yaml per collection, add, validate, and push with --push."""
    ensure_catalog()
    conn = get_conn()
    df = conn.execute(f"SELECT * FROM read_parquet('{SOURCES_TABLE}')").df()
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["src"], row["base"]), []).append(row)
    names = {g: _adm0_name(conn, r) for g, r in groups.items()}
    conn.close()
    for src in sorted({src for src, _ in groups}):
        write_metadata(
            CATALOG_DIR / src,
            title=SRC_NAMES[src],
            description=SRC_DESCRIPTIONS[src],
            **license_fields(None, None),
        )
    stale = stale_collections()
    added = [
        f"{src}/{base}"
        for (src, base), group in sorted(groups.items())
        if _add(src, base, group, names[src, base] or base.upper(), stale)
    ]
    logger.info("publish: %d collection(s) changed: %s", len(added), added)
    if added:
        # portolan treats a readme/check PATH as the catalog root, so run them whole.
        portolan("metadata", "validate")
        portolan("readme")
        # --fix reports failure while an unfixable warning remains; check decides.
        portolan("check", "--fix", "--metadata", strict=False)
        portolan("check", "--data-scope", "local")
    if app.config.PUSH:
        fieldmaps_publish.push(CATALOG_DIR)


def _adm0_name(conn: duckdb.DuckDBPyConnection, group: list[dict]) -> str | None:
    """Return the adm0_name of a collection's first extended layer."""
    row = next((r for r in group if r["tier"] == "extended"), None)
    if row is None:
        return None
    path = catalog_path(row["src"], "extended", row["key"])
    return conn.execute(
        "SELECT any_value(adm0_name) FROM read_parquet(?)", [str(path)]
    ).fetchall()[0][0]


def _add(src: str, base: str, group: list[dict], title: str, stale: set[str]) -> bool:
    """Write metadata.yaml, then tile and `portolan add` if anything changed."""
    row = next((r for r in group if r["tier"] == "original"), group[0])
    lvl = max(r["src_lvl"] for r in group)
    providers = [
        {"name": row[col], "roles": [role]}
        for col, role in (("src_name", "producer"), ("src_name1", "processor"))
        if row[col]
    ]
    files = "; ".join(f"{r['key']}_{r['tier']}: {TIERS[r['tier']]}" for r in group)
    folder = CATALOG_DIR / src / base
    meta_changed = write_metadata(
        folder,
        title=title,
        description=f"{SRC_NAMES[src]}, admin level {lvl}. {files}.",
        **license_fields(row["src_lic"], row["src_url"]),
        providers=[*providers, HOST],
        source_url=row["via"],
        keywords=[row["iso3"], src, f"adm{lvl}"],
    )
    if not (
        app.config.FORCE_PMTILES
        or meta_changed
        or f"{src}/{base}" in stale
        or not (folder / "versions.json").exists()
    ):
        return False
    stamps = [r["src_update"] or r["src_date"] for r in group]
    stamp = max((s for s in stamps if s), default=None)
    when = ["--datetime", str(stamp)[:10]] if stamp else []
    force = ["--force"] if app.config.FORCE_PMTILES else []
    tile_collection(folder, force=app.config.FORCE_PMTILES)
    portolan("add", f"{src}/{base}", *when, *force)
    return True


if __name__ == "__main__":
    main()
