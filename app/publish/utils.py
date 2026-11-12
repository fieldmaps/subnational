"""Shared portolan helpers for the sources and export stages."""

import json
import os
import subprocess
from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory

import tylertoo

import app.config
from app.config import CATALOG_DIR

from . import fieldmaps_publish
from .config import (
    CATALOG_DESCRIPTION,
    CATALOG_ID,
    CATALOG_TITLE,
    CATALOG_URL,
    CONTACT,
    HOST,
    LICENSE_URLS,
    PMTILES_MAX_ZOOM,
    SPDX,
)

logger = getLogger(__name__)

ISO3_DIR = CATALOG_DIR / "iso3"

_CONFIG_YAML = f"""conversion:
  vector:
    add_bbox: false
    sort: none
pmtiles:
  max_zoom: {PMTILES_MAX_ZOOM}
"""


def portolan(*args: str, strict: bool = True) -> dict:
    """Run a portolan command in catalog/ and return its JSON envelope."""
    if args and args[0] == "add":
        return fieldmaps_publish.add(CATALOG_DIR, *args[1:], strict=strict)
    return fieldmaps_publish.run(CATALOG_DIR, *args, strict=strict)


def tile_collection(folder: Path, *, force: bool = False) -> None:
    """Tile each <stem>.parquet in folder as <stem>.pmtiles when missing or older."""
    for parquet in sorted(folder.glob("*.parquet")):
        pmtiles = parquet.with_suffix(".pmtiles")
        if (
            force
            or not pmtiles.exists()
            or pmtiles.stat().st_mtime < parquet.stat().st_mtime
        ):
            _tile(parquet, pmtiles)


def _tile(parquet: Path, pmtiles: Path) -> None:
    """Tile one GeoParquet with tylertoo, every boundary at every zoom."""
    with TemporaryDirectory() as tmp:
        overview = Path(tmp) / "overview.parquet"
        tylertoo.overview(
            str(parquet),
            str(overview),
            max_zoom=PMTILES_MAX_ZOOM,
            density_drop=False,
            line_thinning=0,
            line_visibility=0,
            polygon_thinning=0,
            polygon_visibility=0,
        )
        tylertoo.export_pmtiles(
            str(overview),
            str(pmtiles),
            layer_name=parquet.stem,
            tile_size_limit=None,
        )


def sync_catalog() -> None:
    """Clone or pull catalog/ from PORTOLAN_REMOTE; skip when it is unset."""
    remote = os.getenv("PORTOLAN_REMOTE")
    if not remote:
        logger.warning("PORTOLAN_REMOTE unset, using local catalog/ as is")
        return
    if (CATALOG_DIR / "catalog.json").exists():
        # Collections with unpushed local changes refuse to pull; keep them as is.
        envelope = portolan("pull", remote, strict=False)
        if not envelope["success"]:
            logger.warning("pull skipped unpushed collections: %s", envelope)
        return
    result = subprocess.run(
        ["portolan", "clone", remote, str(CATALOG_DIR)], check=False, text=True
    )
    if result.returncode:
        msg = f"portolan clone {remote} exited {result.returncode}"
        raise RuntimeError(msg)


def write_metadata(folder: Path, **fields: object) -> bool:
    """Write folder/.portolan/metadata.yaml when it differs; return whether it did."""
    fields = {"contact": CONTACT, **fields}
    path = folder / ".portolan" / "metadata.yaml"
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fields.items()]
    text = "\n".join(lines) + "\n"
    if path.exists() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def stale_collections() -> set[str]:
    """Return collections whose files differ from versions.json, README aside.

    portolan readme rewrites each README after add records it, so it always differs.
    """
    envelope = portolan("status", "--offline")
    return {
        c["collection"]
        for c in envelope["data"]["collections"]
        if set(c["modified_files"]) - {"README.md"}
        or c["untracked_files"]
        or c["deleted_files"]
    }


def finalize(*, changed: bool) -> None:
    """Validate, readme and check the catalog if changed, then push with --push."""
    if changed:
        # portolan treats a readme/check PATH as the catalog root, so run them whole.
        portolan("metadata", "validate")
        portolan("readme")
        # --fix reports failure while an unfixable warning remains; check decides.
        portolan("check", "--fix", "--metadata", strict=False)
        portolan("check", "--data-scope", "local")
    if app.config.PUSH:
        fieldmaps_publish.push(CATALOG_DIR)


def license_fields(src_lic: str | None, src_url: str | None) -> dict:
    """Map a source license string to SPDX, or `other` linking to its terms."""
    spdx = SPDX.get(src_lic or "")
    if spdx:
        return {
            "license": spdx,
            "license_url": f"https://spdx.org/licenses/{spdx}.html",
        }
    url = LICENSE_URLS.get(src_lic or "") or src_url or CATALOG_URL
    return {"license": "other", "license_url": url}


def ensure_catalog() -> None:
    """Initialize catalog/ once, then rewrite its root config and metadata."""
    if not (CATALOG_DIR / "catalog.json").exists():
        CATALOG_DIR.mkdir(parents=True, exist_ok=True)
        portolan(
            "init", "--auto", "--id", CATALOG_ID, "--title", CATALOG_TITLE,
            "--license", "other", "--license-url", CATALOG_URL,
        )  # fmt: skip
    (CATALOG_DIR / ".portolan" / "config.yaml").write_text(_CONFIG_YAML)
    write_metadata(
        CATALOG_DIR,
        title=CATALOG_TITLE,
        description=CATALOG_DESCRIPTION,
        license="other",
        license_url=CATALOG_URL,
        providers=[HOST],
    )
