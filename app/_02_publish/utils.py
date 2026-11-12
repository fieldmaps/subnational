"""Shared portolan helpers for the publish and export stages."""

import json
import os
import subprocess
from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory

import tylertoo

from app.config import CATALOG_DIR

from . import fieldmaps_publish
from .config import (
    CATALOG_DESCRIPTION,
    CATALOG_ID,
    CATALOG_TITLE,
    CATALOG_URL,
    CONTACT,
    HOST,
    PMTILES_MAX_ZOOM,
    SPDX,
)

logger = getLogger(__name__)

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
        portolan("pull", remote)
        return
    result = subprocess.run(
        ["portolan", "clone", remote, str(CATALOG_DIR)], check=False, text=True
    )
    if result.returncode:
        msg = f"portolan clone {remote} exited {result.returncode}"
        raise RuntimeError(msg)


def write_metadata(folder: Path, **fields: object) -> None:
    """Write folder/.portolan/metadata.yaml (JSON values are valid YAML)."""
    fields = {"contact": CONTACT, **fields}
    path = folder / ".portolan" / "metadata.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fields.items()]
    path.write_text("\n".join(lines) + "\n")


def license_fields(src_lic: str | None, src_url: str | None) -> dict:
    """Map a source license string to SPDX, or `other` linking to the source."""
    spdx = SPDX.get(src_lic or "")
    if spdx:
        return {
            "license": spdx,
            "license_url": f"https://spdx.org/licenses/{spdx}.html",
        }
    return {"license": "other", "license_url": src_url or CATALOG_URL}


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
