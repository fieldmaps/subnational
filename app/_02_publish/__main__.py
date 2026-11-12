"""Publish each iso3's selected source layers as catalog/iso3/{base} collections."""

import filecmp
import shutil
from logging import getLogger
from pathlib import Path

import duckdb

import app.config
from app._01_sources.utils import source_meta_path, source_path
from app.config import CATALOG_DIR, SOURCES_TABLE
from app.utils import get_conn

from . import fieldmaps_publish
from .config import (
    HOST,
    ISO3_DESCRIPTION,
    ISO3_TITLE,
    SRC_NAMES,
    SRC_NOTICES,
    TIERS,
)
from .utils import (
    ensure_catalog,
    license_fields,
    portolan,
    stale_collections,
    tile_collection,
    write_metadata,
)

logger = getLogger(__name__)

ISO3_DIR = CATALOG_DIR / "iso3"
_PUBLISHED = (".parquet", ".pmtiles", ".thumb.jpg")


def main() -> None:
    """Copy selected layers into catalog/iso3/, add changed ones, push with --push."""
    ensure_catalog()
    conn = get_conn()
    df = conn.execute(
        f"SELECT * FROM read_parquet('{SOURCES_TABLE}') WHERE selected"
    ).df()
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
    removed = _remove_unselected(set(groups))
    for base, group in groups.items():
        _sync(base, group)
    stale = stale_collections()
    added = [
        f"iso3/{base}"
        for base, group in sorted(groups.items())
        if _add(base, group, names[base] or base.upper(), stale)
    ]
    logger.info("publish: %d collection(s) changed: %s", len(added), added)
    if added or removed or iso3_changed:
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
    path = source_path(row["src"], "extended", row["key"])
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


def _remove_unselected(bases: set[str]) -> list[str]:
    """Remove iso3/{base} collections whose base has no selected source."""
    removed = sorted(
        d.name
        for d in ISO3_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in bases
    )
    for base in removed:
        portolan("rm", "-f", f"iso3/{base}")
    return removed


def _sync(base: str, group: list[dict]) -> None:
    """Copy the selected layers and sidecar into iso3/{base}; drop other layers."""
    folder = ISO3_DIR / base
    folder.mkdir(parents=True, exist_ok=True)
    src = group[0]["src"]
    want = {
        f"{r['key']}_{r['tier']}.parquet": source_path(src, r["tier"], r["key"])
        for r in group
    }
    want[f"{base}_metadata.json"] = source_meta_path(src, base)
    for name, path in want.items():
        dest = folder / name
        if not dest.exists() or not filecmp.cmp(path, dest):
            shutil.copy2(path, dest)
    stems = {Path(n).stem for n in want if n.endswith(".parquet")}
    versions = folder / "versions.json"
    tracked = versions.read_text() if versions.exists() else ""
    for f in sorted(folder.iterdir()):
        stem = f.name.removesuffix(".thumb.jpg").rsplit(".", 1)[0]
        if f.name.endswith(_PUBLISHED) and stem not in stems:
            if f'"{f.name}"' in tracked:
                portolan("rm", "-f", f"iso3/{base}/{f.name}")
            else:
                f.unlink()


def _add(base: str, group: list[dict], title: str, stale: set[str]) -> bool:
    """Write metadata.yaml, then tile and `portolan add` if anything changed."""
    src = group[0]["src"]
    row = next((r for r in group if r["tier"] == "original"), group[0])
    lvl = max(r["src_lvl"] for r in group)
    providers = [
        {"name": row[col], "roles": [role]}
        for col, role in (("src_name", "producer"), ("src_name1", "processor"))
        if row[col]
    ]
    files = "; ".join(f"{r['key']}_{r['tier']}: {TIERS[r['tier']]}" for r in group)
    folder = ISO3_DIR / base
    notice = f" {SRC_NOTICES[src]}" if src in SRC_NOTICES else ""
    meta_changed = write_metadata(
        folder,
        title=title,
        description=f"{SRC_NAMES[src]}, admin level {lvl}. {files}.{notice}",
        **license_fields(row["src_lic"], row["src_url"]),
        providers=[*providers, HOST],
        source_url=row["via"],
        keywords=[row["iso3"], src, f"adm{lvl}"],
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
    # add only re-applies a changed metadata.yaml to a collection with --force.
    force = ["--force"] if app.config.FORCE_PMTILES or meta_changed else []
    tile_collection(folder, force=app.config.FORCE_PMTILES)
    portolan("add", f"iso3/{base}", *when, *force)
    return True


if __name__ == "__main__":
    main()
