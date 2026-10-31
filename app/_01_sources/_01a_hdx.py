"""Back up each iso3's full-coverage layer from source.coop/hdx/cod-ab."""

from logging import getLogger
from pathlib import Path

import duckdb

from app.config import MAX_LVL

from .config import (
    DOWNLOAD_DIR,
    HDX_META_NAME,
    HDX_PACKAGE,
    HDX_SRC_URL,
    SC_BASE,
    SC_URL,
    SRC,
)
from .schema import conform, write_meta
from .utils import catalog_path, download, get_json, meta_path

logger = getLogger(__name__)


def load_hdx(conn: duckdb.DuckDBPyConnection) -> None:
    """Write catalog/cod-ab/{iso3}/ with both tiers and its metadata sidecar."""
    metadata = _load_metadata(conn)
    catalog = get_json(f"{SC_BASE}/extended/catalog.json")
    iso3s = sorted(
        link["href"].split("/")[1]
        for link in catalog["links"]
        if link["rel"] == "child"
    )
    for key in iso3s:
        meta = metadata.get(key.upper())
        if meta is None or meta["src_lvl"] is None:
            logger.warning("%s: not in HDX metadata CSV, skipping", key)
            continue
        lvl = meta["src_lvl"]
        if not 1 <= lvl <= MAX_LVL:
            logger.warning("%s: admin_level_full=%s, skipping", key, lvl)
            continue
        layer = f"{key}/latest/{key}_admin{lvl}"
        ext_coll = get_json(f"{SC_BASE}/extended/{layer}/collection.json")
        ext = _fetch(ext_coll, f"{SC_BASE}/extended/{layer}", "extended")
        conform(
            conn,
            f"SELECT * FROM read_parquet('{ext}')",
            lvl,
            catalog_path(SRC, "extended", key),
        )
        orig_coll = get_json(f"{SC_BASE}/original/{layer}/collection.json")
        orig = _fetch(orig_coll, f"{SC_BASE}/original/{layer}", "original")
        _write_original(conn, orig, lvl, catalog_path(SRC, "original", key))
        langs = conn.execute(
            f"SELECT any_value(lang), any_value(lang1), any_value(lang2) "
            f"FROM read_parquet('{ext}')"
        ).fetchall()[0]
        row = {
            "key": key,
            "iso3": key.upper(),
            "src": SRC,
            **meta,
            **dict(zip(("src_lang", "src_lang1", "src_lang2"), langs, strict=True)),
            "src_lic": ext_coll["license"],
            "src_url": HDX_SRC_URL,
            "src_grp": "COD",
        }
        for tier in ("extended", "original"):
            row |= {"tier": tier, "via": f"{SC_URL}/{tier}/{layer}"}
            write_meta(row, meta_path(SRC, key))


def _fetch(coll: dict, base: str, tier: str) -> Path:
    """Download a STAC collection's data asset into tmp/sources/hdx/{tier}/."""
    asset = next(a for a in coll["assets"].values() if "data" in a.get("roles", []))
    url = f"{base}/{asset['href'].removeprefix('./')}"
    dest = DOWNLOAD_DIR / "hdx" / tier / url.rsplit("/", 1)[1]
    return download(url, dest, asset.get("file:size"))


def _write_original(
    conn: duckdb.DuckDBPyConnection, raw: Path, lvl: int, dest: Path
) -> None:
    """Write the published original in the extended schema."""
    conform(conn, f"SELECT * FROM read_parquet('{raw}')", lvl, dest)


def _load_metadata(conn: duckdb.DuckDBPyConnection) -> dict:
    """Return {iso3: src_* dict} from the HDX COD-AB global metadata CSV."""
    resources = get_json(HDX_PACKAGE)["result"]["resources"]
    url = next(r["url"] for r in resources if r["name"] == HDX_META_NAME)
    csv = download(url, DOWNLOAD_DIR / HDX_META_NAME)
    rows = conn.execute(f"""--sql
        SELECT
            country_iso3,
            TRY_CAST(admin_level_full AS INTEGER),
            TRY_CAST(date_source AS DATE),
            TRY_CAST(date_updated AS DATE),
            source,
            contributor
        FROM read_csv('{csv}', nullstr=['', '#N/A'])
        WHERE country_iso3 IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY country_iso3
            ORDER BY TRY_CAST(date_updated AS DATE) DESC NULLS LAST
        ) = 1
    """).fetchall()
    keys = ("src_lvl", "src_date", "src_update", "src_name", "src_name1")
    return {row[0]: dict(zip(keys, row[1:], strict=True)) for row in rows}
