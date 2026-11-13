"""Register each catalog/iso3/{base} collection with portolan."""

import json
from logging import getLogger
from pathlib import Path

import duckdb

import app.config
from app._01_sources.schema import SOURCES_SQL
from app._01_sources.utils import catalog_path
from app.publish.config import (
    HOST,
    ISO3_DESCRIPTION,
    ISO3_TITLE,
    SRC_NAMES,
    SRC_NOTICES,
    TIERS,
)
from app.publish.utils import (
    ISO3_DIR,
    ensure_catalog,
    finalize,
    license_fields,
    portolan,
    stale_collections,
    tile_collection,
    write_metadata,
)
from app.utils import get_conn

logger = getLogger(__name__)


def publish() -> None:
    """Write metadata, add changed collections, check, and push with --push."""
    ensure_catalog()
    conn = get_conn()
    df = conn.execute(SOURCES_SQL).df()
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["base"], []).append(row)
    names = {base: _adm0_name(conn, group) for base, group in groups.items()}
    conn.close()
    iso3_changed = write_metadata(
        ISO3_DIR,
        title=ISO3_TITLE,
        description=f"{ISO3_DESCRIPTION}\n\n{_sources_table(groups, names)}",
        **license_fields(None, None),
    )
    stale = stale_collections()
    added = [
        f"iso3/{base}"
        for base, group in sorted(groups.items())
        if _add(base, group, names[base] or base.upper(), stale)
    ]
    logger.info("publish: %d collection(s) changed: %s", len(added), added)
    finalize(changed=bool(added) or iso3_changed)


def _adm0_name(conn: duckdb.DuckDBPyConnection, group: list[dict]) -> str | None:
    """Return the adm0_name of a collection's first extended layer."""
    row = next((r for r in group if r["tier"] == "extended"), None)
    if row is None:
        return None
    path = catalog_path("extended", row["key"])
    return conn.execute(
        "SELECT any_value(adm0_name) FROM read_parquet(?)", [str(path)]
    ).fetchall()[0][0]


def _sources_table(groups: dict[str, list[dict]], names: dict) -> str:
    """Return a markdown table of each base iso3's published source."""
    head = ("ISO3", "Name", "Source", "Admin level", "Source date", "Updated")
    lines = ["| " + " | ".join((*head, "Producer", "License")) + " |"]
    lines.append("|" + "---|" * (len(head) + 2))
    for base, group in sorted(groups.items()):
        row = next((r for r in group if r["tier"] == "original"), group[0])
        cells = (
            base.upper(),
            names[base] or "",
            row["src"],
            str(max(r["src_lvl"] for r in group)),
            str(row["src_date"] or "")[:10],
            str(row["src_update"] or "")[:10],
            row["src_name"] or "",
            _license_name(row["src_lic"], row["src_url"]),
        )
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines)


def _license_name(src_lic: str | None, src_url: str | None) -> str:
    """Return the SPDX id, or the source's own license name for `other`."""
    spdx = license_fields(src_lic, src_url)["license"]
    return src_lic if spdx == "other" and src_lic else spdx


def _add(base: str, group: list[dict], title: str, stale: set[str]) -> bool:
    """Write metadata.yaml, then tile and `portolan add` if anything changed."""
    srcs = list(dict.fromkeys(r["src"] for r in group))
    row = next((r for r in group if r["tier"] == "original"), group[0])
    lvl = max(r["src_lvl"] for r in group)
    providers = list(
        {
            r[col]: {"name": r[col], "roles": [role]}
            for r in group
            for col, role in (("src_name", "producer"), ("src_name1", "processor"))
            if r[col]
        }.values()
    )
    files = "; ".join(f"{r['key']}_{r['tier']}: {TIERS[r['tier']]}" for r in group)
    folder = ISO3_DIR / base
    names = " and ".join(SRC_NAMES[s] for s in srcs)
    notice = "".join(f" {SRC_NOTICES[s]}" for s in srcs if s in SRC_NOTICES)
    meta_changed = write_metadata(
        folder,
        title=title,
        description=f"{names}, admin level {lvl}. {files}.{notice}",
        **license_fields(row["src_lic"], row["src_url"]),
        providers=[*providers, HOST],
        source_url=row["via"],
        keywords=[row["iso3"], *srcs, f"adm{lvl}"],
    )
    if not (
        app.config.FORCE_PMTILES
        or meta_changed
        or f"iso3/{base}" in stale
        or not (folder / "versions.json").exists()
    ):
        return False
    stamps = [r["src_update"] or r["src_date"] for r in group]
    stamp = max((s for s in stamps if s), default=None)
    when = ["--datetime", str(stamp)[:10]] if stamp else []
    tile_collection(folder, force=app.config.FORCE_PMTILES)
    _reset_style(folder)
    # Without --force, add skips a changed metadata.yaml or sidecar JSON.
    portolan("add", f"iso3/{base}", *when, "--force")
    return True


def _reset_style(folder: Path) -> None:
    """Make add rebuild the style and thumbnail when they miss the first extended layer.

    portolan builds both from the first data asset in collection.json.
    """
    first = min(p.stem for p in folder.glob("*_extended.parquet"))
    style = folder / "styles" / "default.json"
    if not style.exists() or f"/{first}.pmtiles" in style.read_text():
        return
    path = folder / "collection.json"
    coll = json.loads(path.read_text())
    coll["assets"] = dict(
        sorted(coll["assets"].items(), key=lambda kv: ("original" in kv[0], kv[0]))
    )
    coll["links"] = [
        link
        for link in coll["links"]
        if link["rel"] != "pmtiles" or (folder / link["href"]).exists()
    ]
    path.write_text(json.dumps(coll, indent=2) + "\n")
    style.unlink()
    for thumb in folder.glob("*.thumb.jpg"):
        if thumb.name != f"{first}.thumb.jpg":
            portolan("rm", "-f", f"iso3/{folder.name}/{thumb.name}")
