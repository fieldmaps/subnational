"""Back up each iso3's full-coverage layer from source.coop/hdx/cod-ab."""

import json
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
    SC_LOCAL,
    SC_URL,
    SRC,
)
from .schema import conform, write_meta
from .utils import catalog_path, download, get_json, meta_path

logger = getLogger(__name__)

_TIERS = ("extended", "original")
_LANGS = ("src_lang", "src_lang1", "src_lang2")


def load_hdx(conn: duckdb.DuckDBPyConnection) -> None:
    """Write catalog/cod-ab/{iso3}/ with both tiers and its metadata sidecar."""
    metadata = _load_metadata(conn)
    catalog = _sc_json("extended/catalog.json")
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
        ext_coll = _sc_json(f"extended/{layer}/collection.json")
        row = {
            "key": key,
            "iso3": key.upper(),
            "src": SRC,
            **meta,
            "src_lic": ext_coll["license"],
            "src_url": HDX_SRC_URL,
            "src_grp": "COD",
        }
        if _is_current(key, row, layer):
            continue
        ext = _fetch(ext_coll, f"extended/{layer}", "extended")
        conform(
            conn,
            f"SELECT * FROM read_parquet('{ext}')",
            lvl,
            catalog_path(SRC, "extended", key),
        )
        orig_coll = _sc_json(f"original/{layer}/collection.json")
        orig = _fetch(orig_coll, f"original/{layer}", "original")
        _write_original(conn, orig, lvl, catalog_path(SRC, "original", key))
        langs = conn.execute(
            f"SELECT any_value(lang), any_value(lang1), any_value(lang2) "
            f"FROM read_parquet('{ext}')"
        ).fetchall()[0]
        row |= dict(zip(_LANGS, langs, strict=True))
        for tier in _TIERS:
            row |= {"tier": tier, "via": f"{SC_URL}/{tier}/{layer}"}
            write_meta(row, meta_path(SRC, key))


def _is_current(key: str, row: dict, layer: str) -> bool:
    """Return whether both tiers exist and the sidecar already holds this row."""
    path = meta_path(SRC, key)
    if not path.exists() or not all(catalog_path(SRC, t, key).exists() for t in _TIERS):
        return False
    have = {r["tier"]: r for r in json.loads(path.read_text())["rows"]}
    for tier in _TIERS:
        want = row | {"tier": tier, "via": f"{SC_URL}/{tier}/{layer}"}
        want = json.loads(json.dumps(want, default=lambda v: v.isoformat()[:10]))
        old = have.get(tier, {})
        if any(old.get(k) != v for k, v in want.items()):
            return False
    return True


def _sc_json(rel: str) -> dict:
    """Read a cod-ab STAC file from SC_LOCAL if present, else from source.coop."""
    local = SC_LOCAL / rel
    if local.exists():
        return json.loads(local.read_text())
    return get_json(f"{SC_BASE}/{rel}")


def _fetch(coll: dict, rel: str, tier: str) -> Path:
    """Return a collection's data asset from SC_LOCAL, else download it to tmp."""
    asset = next(a for a in coll["assets"].values() if "data" in a.get("roles", []))
    rel = f"{rel}/{asset['href'].removeprefix('./')}"
    local = SC_LOCAL / rel
    if local.exists():
        return local
    dest = DOWNLOAD_DIR / "hdx" / tier / rel.rsplit("/", 1)[1]
    return download(f"{SC_BASE}/{rel}", dest, asset.get("file:size"))


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
