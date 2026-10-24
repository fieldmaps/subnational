"""Fill iso3 not on source.coop from legacy data.fieldmaps.io COD / geoBoundaries."""

import json
import subprocess
from datetime import date
from logging import getLogger
from pathlib import Path

import duckdb

from .config import DOWNLOAD_DIR, MAX_LVL
from .utils import (
    ADMIN_SCHEMA_SQL,
    catalog_path,
    download,
    get_json,
    write_extended,
)

logger = getLogger(__name__)


def load_legacy(
    conn: duckdb.DuckDBPyConnection,
    list_url: str,
    src: str,
    covered: set[str],
) -> list[dict]:
    """Write legacy layers for iso3 not in `covered` into catalog/; return their rows.

    Multi-extent entries (e.g. pak_1) get one extended file each and share one
    original, keyed by the base iso3.
    """
    todo = [
        e
        for e in get_json(list_url)
        if e.get("id") and e["iso_3"] not in covered and _valid_lvl(e)
    ]
    rows = []
    for entry in todo:
        key = entry["id"]
        raw = download(entry["e_parquet"], DOWNLOAD_DIR / src / f"{key}.parquet")
        _load_extended(conn, raw, key.upper())
        write_extended(conn, key)
        rows.append(
            {
                "key": key,
                "iso3": key.upper(),
                "src": src,
                **{k: entry.get(k) for k in _META_KEYS},
                "src_date": _date(entry.get("src_date")),
                "src_update": _date(entry.get("src_update")),
                "via_extended": entry["e_parquet"],
                "via_original": entry.get("o_gpkg"),
            }
        )
    for base in sorted({e["id"].split("_")[0] for e in todo}):
        entries = [e for e in todo if e["id"].split("_")[0] == base and e.get("o_gpkg")]
        if not entries:
            logger.warning("%s: no original layer", base)
            continue
        lvl = max(e["src_lvl"] for e in entries)
        zipped = download(entries[0]["o_gpkg"], DOWNLOAD_DIR / src / f"{base}.gpkg.zip")
        _write_original(zipped, base, lvl)
    return rows


_META_KEYS = (
    "src_lvl",
    "src_name",
    "src_name1",
    "src_lic",
    "src_url",
)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _valid_lvl(entry: dict) -> bool:
    lvl = entry.get("src_lvl")
    if lvl is None or not 1 <= lvl <= MAX_LVL:
        logger.warning("%s: src_lvl=%s, skipping", entry["id"], lvl)
        return False
    return True


def _load_extended(conn: duckdb.DuckDBPyConnection, raw: Path, iso3: str) -> None:
    """Project one legacy extended parquet onto the `admin` schema."""
    conn.execute(ADMIN_SCHEMA_SQL)
    described = conn.execute(f"DESCRIBE FROM read_parquet('{raw}')").fetchall()
    stage = {row[0] for row in described}
    cols = [row[0] for row in conn.execute("DESCRIBE admin").fetchall()]
    parts = []
    for col in cols:
        if col == "iso3":
            parts.append(f"'{iso3}' AS iso3")
        elif col == "geom":
            parts.append("geom" if "geom" in stage else "geometry AS geom")
        elif col in stage:
            parts.append(f'"{col}"')
        else:
            parts.append(f'NULL AS "{col}"')
    conn.execute(
        f"INSERT INTO admin SELECT {', '.join(parts)} FROM read_parquet('{raw}')"
    )


def _write_original(zipped: Path, base: str, lvl: int) -> None:
    """Write `{base}_adm{lvl}` (or the finest layer) as Hilbert-sorted GeoParquet."""
    src = f"/vsizip/{zipped}"
    info = subprocess.run(
        ["gdal", "vector", "info", "--format", "json", "--summary", src],
        check=True,
        capture_output=True,
        text=True,
    )
    layers = {lyr["name"] for lyr in json.loads(info.stdout)["layers"]}
    layer = f"{base}_adm{lvl}"
    if layer not in layers:
        layer = max(
            (n for n in layers if n.startswith(f"{base}_adm")),
            key=lambda n: int(n.rsplit("adm", 1)[1]),
        )
        logger.warning("%s: no %s_adm%d, using %s", base, base, lvl, layer)
    dest = catalog_path("original", base)
    subprocess.run(
        [
            "gdal", "vector", "sort", "--quiet", "--overwrite", "--method", "hilbert",
            "--layer", layer, "--output-format", "Parquet",
            "--lco", "COMPRESSION=ZSTD", src, str(dest),
        ],
        check=True,
    )  # fmt: skip
