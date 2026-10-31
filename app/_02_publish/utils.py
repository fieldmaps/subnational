"""Shared portolan helpers for the publish and export stages."""

import json
import os
import shutil
import subprocess
from logging import getLogger
from pathlib import Path

from app.config import CATALOG_DIR

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
_LAUNCHER = Path(__file__).with_name("tylertoo_portolan.py")


def portolan(*args: str, strict: bool = True) -> dict:
    """Run a portolan command in catalog/ and return its JSON envelope."""
    # The launcher runs in portolan's tool env, found via its entry point shebang.
    python = Path(shutil.which("portolan") or "portolan").read_text().split()[0][2:]
    result = subprocess.run(
        [python, str(_LAUNCHER), "--format", "json", *args],
        cwd=CATALOG_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        msg = f"portolan {' '.join(args)} exited {result.returncode}: {result.stderr}"
        raise RuntimeError(msg) from e
    if strict and not envelope["success"]:
        msg = f"portolan {' '.join(args)} failed: {envelope['errors']}"
        raise RuntimeError(msg)
    return envelope


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
