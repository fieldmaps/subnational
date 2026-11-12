"""Refresh each iso3's catalog collection from source.coop/hdx/cod-ab."""

import json
from logging import getLogger
from pathlib import Path

import duckdb

from app.config import KEEP, MAX_LVL
from app.publish.utils import portolan

from .config import (
    COD_AB_DATA,
    COD_AB_SRC_URL,
    COD_AB_URL,
    DOWNLOAD_DIR,
    SRC,
)
from .schema import conform, write_meta
from .utils import catalog_path, download, get_json, meta_path, published_src

logger = getLogger(__name__)

_TIERS = ("extended", "original")
_LANGS = ("src_lang", "src_lang1", "src_lang2")


def load_cod_ab(conn: duckdb.DuckDBPyConnection) -> None:
    """Write catalog/iso3/{iso3}/ from cod-ab when its metadata or data changed."""
    catalog = get_json(f"{COD_AB_DATA}/extended/catalog.json")
    iso3s = sorted(
        link["href"].split("/")[1]
        for link in catalog["links"]
        if link["rel"] == "child"
    )
    for key in iso3s:
        if key in KEEP:
            continue
        meta = _metadata(key)
        lvl = meta["src_lvl"]
        if lvl is None or not 1 <= lvl <= MAX_LVL:
            logger.warning("%s: admin_level_full=%s, skipping", key, lvl)
            continue
        layer = f"{key}/latest/{key}_admin{lvl}"
        colls = {
            t: get_json(f"{COD_AB_DATA}/{t}/{layer}/collection.json") for t in _TIERS
        }
        row = {
            "key": key,
            "iso3": key.upper(),
            "src": SRC,
            **meta,
            "src_lic": colls["extended"]["license"],
            "src_url": COD_AB_SRC_URL,
            "src_grp": "COD",
        }
        rows = {
            t: row
            | {
                "tier": t,
                "via": f"{COD_AB_URL}/{t}/{layer}",
                "via_checksum": _data(c)["file:checksum"],
            }
            for t, c in colls.items()
        }
        if _is_current(key, rows):
            continue
        src = published_src(key)
        if src not in (None, SRC):
            logger.info("%s: replacing %s with %s", key, src, SRC)
            portolan("rm", "-f", f"iso3/{key}")
        paths = {t: _fetch(c, f"{t}/{layer}", t) for t, c in colls.items()}
        for tier, path in paths.items():
            dest = catalog_path(tier, key)
            conform(conn, f"SELECT * FROM read_parquet('{path}')", lvl, dest)
        langs = conn.execute(
            f"SELECT any_value(lang), any_value(lang1), any_value(lang2) "
            f"FROM read_parquet('{paths['extended']}')"
        ).fetchall()[0]
        for tier_row in rows.values():
            write_meta(tier_row | dict(zip(_LANGS, langs, strict=True)), meta_path(key))


def _is_current(key: str, rows: dict[str, dict]) -> bool:
    """Return whether both tiers exist and the sidecar already holds these rows."""
    path = meta_path(key)
    if not path.exists() or not all(catalog_path(t, key).exists() for t in _TIERS):
        return False
    have = {r["tier"]: r for r in json.loads(path.read_text())["rows"]}
    for tier, row in rows.items():
        want = json.loads(json.dumps(row, default=lambda v: v.isoformat()[:10]))
        if any(have.get(tier, {}).get(k) != v for k, v in want.items()):
            return False
    return True


def _data(coll: dict) -> dict:
    """Return a cod-ab collection's data asset."""
    return next(a for a in coll["assets"].values() if "data" in a.get("roles", []))


def _fetch(coll: dict, rel: str, tier: str) -> Path:
    """Download a collection's data asset to tmp, replacing any earlier copy."""
    name = _data(coll)["href"].removeprefix("./")
    dest = DOWNLOAD_DIR / SRC / tier / name
    dest.unlink(missing_ok=True)
    return download(f"{COD_AB_DATA}/{rel}/{name}", dest, _data(coll).get("file:size"))


def _metadata(key: str) -> dict:
    """Return the src_* fields from cod-ab's original/{iso3}/latest catalog."""
    cat = get_json(f"{COD_AB_DATA}/original/{key}/latest/catalog.json")
    fields = {
        "src_lvl": "admin_level_full",
        "src_date": "date_source",
        "src_update": "date_updated",
        "src_name": "source",
        "src_name1": "contributor",
    }
    return {k: cat.get(f"cod_ab:{v}") for k, v in fields.items()}
