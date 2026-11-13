"""Refresh each iso3's catalog collection from source.coop/hdx/cod-ab."""

import json
from logging import getLogger
from pathlib import Path

import duckdb
from topo_tools.api import edge_extend

from app.config import KEEP, MAX_LVL, PARQUET_OPTS, PARTS
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
        parts = PARTS.get(key, ())
        # A split derives every part from the original layer.
        via = {t: "original" if len(parts) > 1 else t for t in _TIERS}
        tiers = {
            t: row
            | {
                "tier": t,
                "via": f"{COD_AB_URL}/{via[t]}/{layer}",
                "via_checksum": _data(colls[via[t]])["file:checksum"],
            }
            for t in _TIERS
        }
        ext_keys = [p.lower() for p in parts] or [key]
        rows = {("original", key): tiers["original"]} | {
            ("extended", k): tiers["extended"] | {"key": k} for k in ext_keys
        }
        if _is_current(key, rows):
            continue
        src = published_src(key)
        if src not in (None, SRC):
            logger.info("%s: replacing %s with %s", key, src, SRC)
            portolan("rm", "-f", f"iso3/{key}")
        _drop_stale(key, rows)
        paths = {t: _fetch(c, f"{t}/{layer}", t) for t, c in colls.items()}
        original = f"SELECT * FROM read_parquet('{paths['original']}')"
        conform(conn, original, lvl, catalog_path("original", key))
        if len(parts) > 1:
            _split(conn, paths["original"], lvl, parts)
        else:
            extended = f"SELECT * FROM read_parquet('{paths['extended']}')"
            conform(conn, extended, lvl, catalog_path("extended", ext_keys[0]))
        langs = conn.execute(
            f"SELECT any_value(lang), any_value(lang1), any_value(lang2) "
            f"FROM read_parquet('{paths['extended']}')"
        ).fetchall()[0]
        for meta in rows.values():
            write_meta(meta | dict(zip(_LANGS, langs, strict=True)), meta_path(key))


def _is_current(key: str, rows: dict[tuple[str, str], dict]) -> bool:
    """Return whether every layer exists and the sidecar holds exactly these rows."""
    path = meta_path(key)
    if not path.exists() or not all(catalog_path(t, k).exists() for t, k in rows):
        return False
    have = {(r["tier"], r["key"]): r for r in json.loads(path.read_text())["rows"]}
    if have.keys() != rows.keys():
        return False
    for tk, row in rows.items():
        want = json.loads(json.dumps(row, default=lambda v: v.isoformat()[:10]))
        if any(have[tk].get(k) != v for k, v in want.items()):
            return False
    return True


def _drop_stale(key: str, rows: dict[tuple[str, str], dict]) -> None:
    """Remove a collection's layers and sidecar rows that `rows` no longer lists."""
    path = meta_path(key)
    if not path.exists():
        return
    have = json.loads(path.read_text())["rows"]
    for r in have:
        if (r["tier"], r["key"]) in rows:
            continue
        stem = catalog_path(r["tier"], r["key"]).with_suffix("")
        for f in stem.parent.glob(f"{stem.name}.*"):
            portolan("rm", "-f", f"iso3/{key}/{f.name}")
    keep = [r for r in have if (r["tier"], r["key"]) in rows]
    path.write_text(json.dumps({"rows": keep}, indent=2) + "\n")


def _split(
    conn: duckdb.DuckDBPyConnection, original: Path, lvl: int, parts: tuple
) -> None:
    """Write one extended layer per ADM0 clip part from the units inside it."""
    from app._02_build._02a_inputs import adm0_clip_sql  # noqa: PLC0415 (import cycle)

    for part in parts:
        subset = DOWNLOAD_DIR / SRC / "split" / f"{part.lower()}.parquet"
        subset.parent.mkdir(parents=True, exist_ok=True)
        conn.execute(
            f"""--sql
            COPY (
                SELECT o.* FROM read_parquet('{original}') o
                JOIN ({adm0_clip_sql()}) a
                  ON a.adm0_src = ?
                 AND ST_Within(ST_PointOnSurface(o.geometry), a.geometry)
            ) TO '{subset}' {PARQUET_OPTS}
        """,
            [part],
        )
        extended = subset.with_name(f"{part.lower()}_extended.parquet")
        edge_extend(subset, extended)
        select = f"SELECT * FROM read_parquet('{extended}')"
        conform(conn, select, lvl, catalog_path("extended", part.lower()))


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
