"""One-time copy of data.fieldmaps.io COD and geoBoundaries layers into sources/.

Run: uv run python -m scripts.migrate_fieldmaps [--keys alb,pak_1] [--skip-publish]
"""

from argparse import ArgumentParser
from datetime import date
from logging import getLogger

import duckdb
import httpx2

from app import _02_publish
from app._01_sources.config import DOWNLOAD_DIR
from app._01_sources.schema import conform, write_meta
from app._01_sources.sources import build_sources_table
from app._01_sources.utils import download, get_json, source_meta_path, source_path
from app._03_build._03a_inputs import adm0_path
from app._03_build.config import ADM0_HUMANITARIAN
from app.utils import get_conn

logger = getLogger(__name__)

# src folder -> (list URL, tmp/sources subfolder, src_grp)
LISTS = {
    "cod-ab-legacy": ("https://data.fieldmaps.io/cod.json", "cod", "COD"),
    "geoboundaries": (
        "https://data.fieldmaps.io/geoboundaries.json",
        "geoboundaries",
        "geoBoundaries",
    ),
}
_META_KEYS = ("src_lvl", "src_name", "src_name1", "src_lic", "src_url")
_LANG_KEYS = ("src_lang", "src_lang1", "src_lang2")


def main() -> None:
    """Migrate every legacy entry (or --keys) into sources/{src}/{base}/."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--keys", type=lambda v: set(v.split(",")), default=None)
    parser.add_argument("--skip-publish", action="store_true")
    args = parser.parse_args()
    conn = get_conn()
    adm0 = adm0_path(ADM0_HUMANITARIAN)
    iso2_sql = f"SELECT DISTINCT iso_3, iso_2 FROM read_parquet('{adm0}')"
    iso2 = dict(conn.execute(iso2_sql).fetchall())
    for src, (list_url, _, _) in LISTS.items():
        entries = [
            e
            for e in get_json(list_url)
            if e.get("id")
            and e.get("src_lvl")
            and (args.keys is None or {e["id"], _base(e)} & args.keys)
        ]
        for entry in entries:
            _migrate_extended(conn, src, entry, iso2.get(entry["iso_3"]))
        for base in sorted({_base(e) for e in entries}):
            group = [e for e in entries if _base(e) == base and e.get("o_gpkg")]
            if group:
                _migrate_original(conn, src, base, group, iso2.get(group[0]["iso_3"]))
            else:
                logger.warning("%s %s: no original layer", src, base)
    build_sources_table(conn)
    conn.close()
    if not args.skip_publish:
        _02_publish.main()


def _base(entry: dict) -> str:
    return entry["id"].split("_")[0]


def _meta(src: str, tier: str, key: str, entry: dict, via: str) -> dict:
    return {
        "key": key,
        "tier": tier,
        "iso3": entry["iso_3"],
        "src": src,
        **{k: entry.get(k) for k in (*_META_KEYS, *_LANG_KEYS)},
        "src_date": _date(entry.get("src_date")),
        "src_update": _date(entry.get("src_update")),
        "src_grp": LISTS[src][2],
        "via": via,
    }


def _migrate_extended(
    conn: duckdb.DuckDBPyConnection, src: str, entry: dict, iso2: str | None
) -> None:
    """Map one legacy extended parquet onto the cod-ab extended schema."""
    folder = LISTS[src][1]
    key, lvl = entry["id"], entry["src_lvl"]
    url, dest = entry["e_parquet"], DOWNLOAD_DIR / folder / f"{key}.parquet"
    try:
        raw = download(url, dest)
    except httpx2.HTTPStatusError:
        # Some list ids (jam_1) are published under the base name only.
        url = url.replace(f"/{key}.parquet", f"/{_base(entry)}.parquet")
        raw = download(url, dest)
    have = {
        row[0]
        for row in conn.execute(f"DESCRIBE FROM read_parquet('{raw}')").fetchall()
    }
    levels = [f"adm{n}_src AS adm{n}_pcode" for n in range(lvl + 1)] + [
        f"adm{n}_{c}"
        for n in range(lvl + 1)
        for c in ("name", "name1", "name2")
        if f"adm{n}_{c}" in have
    ]
    fills = {
        "valid_on": _lit(entry.get("src_date")),
        "lang": _lit(entry.get("src_lang")),
        "lang1": _lit(entry.get("src_lang1")),
        "lang2": _lit(entry.get("src_lang2")),
        "iso2": _lit(iso2),
        "iso3": _lit(entry["iso_3"]),
    }
    select = ", ".join([*levels, *(f"{v} AS {k}" for k, v in fills.items())])
    conform(
        conn,
        f"SELECT {select}, geometry FROM read_parquet('{raw}')",
        lvl,
        source_path(src, "extended", key),
    )
    meta = _meta(src, "extended", key, entry, url)
    write_meta(meta, source_meta_path(src, key))


def _migrate_original(
    conn: duckdb.DuckDBPyConnection,
    src: str,
    base: str,
    group: list[dict],
    iso2: str | None,
) -> None:
    """Map the finest {base}_adm{n} gpkg layer onto the cod-ab extended schema."""
    folder = LISTS[src][1]
    entry = max(group, key=lambda e: e["src_lvl"])
    zipped = download(entry["o_gpkg"], DOWNLOAD_DIR / folder / f"{base}.gpkg.zip")
    gpkg = f"/vsizip/{zipped}"
    meta_sql = f"SELECT layers FROM ST_Read_Meta('{gpkg}')"
    layers = {lyr["name"] for lyr in conn.execute(meta_sql).fetchall()[0][0]}
    layer = f"{base}_adm{entry['src_lvl']}"
    if layer not in layers:
        layer = max(
            (n for n in layers if n.startswith(f"{base}_adm")),
            key=lambda n: int(n.rsplit("adm", 1)[1]),
        )
        logger.warning("%s: no %s_adm%d, using %s", base, base, entry["src_lvl"], layer)
    lvl = int(layer.rsplit("adm", 1)[1])
    query = f"SELECT * FROM ST_Read('{gpkg}', layer='{layer}')"
    have = {row[0] for row in conn.execute(f"DESCRIBE {query}").fetchall()}
    select = _original_columns(src, entry, lvl, have, iso2)
    conform(
        conn,
        f"SELECT {select}, geom AS geometry FROM ({query})",
        lvl,
        source_path(src, "original", base),
    )
    meta = _meta(src, "original", base, entry, entry["o_gpkg"])
    meta["src_lvl"] = lvl
    write_meta(meta, source_meta_path(src, base))


def _original_columns(
    src: str, entry: dict, lvl: int, have: set[str], iso2: str | None
) -> str:
    """Return SELECT items mapping a legacy layer's own columns to cod-ab names."""
    langs = [entry.get(k) for k in _LANG_KEYS]
    cols = []
    for n in range(lvl + 1):
        if src == "geoboundaries":
            cols += [f"adm{n}_id AS adm{n}_pcode", f"adm{n}_name"]
            continue
        cols.append(f'"ADM{n}_PCODE" AS adm{n}_pcode')
        for suffix, lang in zip(("name", "name1", "name2"), langs, strict=True):
            col = f"ADM{n}_{(lang or '').upper()}"
            if lang and col in have:
                cols.append(f'"{col}" AS adm{n}_{suffix}')
    dates = [f'TRY_CAST("{c}" AS TIMESTAMP)' for c in ("VALIDON", "DATE") if c in have]
    valid_to = 'TRY_CAST("VALIDTO" AS TIMESTAMP)' if "VALIDTO" in have else "NULL"
    fills = {
        "valid_on": f"coalesce({', '.join([*dates, _lit(entry.get('src_date'))])})",
        "valid_to": valid_to,
        "lang": _lit(langs[0]),
        "lang1": _lit(langs[1]),
        "lang2": _lit(langs[2]),
        "iso2": _lit(iso2),
        "iso3": _lit(entry["iso_3"]),
    }
    return ", ".join([*cols, *(f"{v} AS {k}" for k, v in fills.items())])


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _lit(value: object) -> str:
    """Return a SQL VARCHAR literal for value, or NULL."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


if __name__ == "__main__":
    main()
