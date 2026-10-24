"""Select each iso3's full-coverage layer from source.coop/hdx/cod-ab."""

from logging import getLogger
from pathlib import Path

import duckdb

from .config import (
    DOWNLOAD_DIR,
    HDX_META_NAME,
    HDX_PACKAGE,
    HDX_SRC_URL,
    MAX_LVL,
    SC_BASE,
    SC_URL,
)
from .utils import (
    ADMIN_SCHEMA_SQL,
    catalog_path,
    download,
    get_json,
    id_gen_ctas_sql,
    write_extended,
)

logger = getLogger(__name__)


def load_hdx(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Write source.coop extended + original layers into catalog/; return their rows."""
    metadata = _load_metadata(conn)
    catalog = get_json(f"{SC_BASE}/extended/catalog.json")
    iso3s = sorted(
        link["href"].split("/")[1]
        for link in catalog["links"]
        if link["rel"] == "child"
    )
    rows = []
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
        url, size = _data_asset(ext_coll, f"{SC_BASE}/extended/{layer}")
        raw = download(url, DOWNLOAD_DIR / "hdx" / url.rsplit("/", 1)[1], size)
        _load_extended(
            conn, raw, iso3=key.upper(), lvl=lvl, meta=meta, lic=ext_coll["license"]
        )
        write_extended(conn, key)
        orig_coll = get_json(f"{SC_BASE}/original/{layer}/collection.json")
        url, size = _data_asset(orig_coll, f"{SC_BASE}/original/{layer}")
        download(url, catalog_path("original", key), size)
        rows.append(
            {
                "key": key,
                "iso3": key.upper(),
                "src": "hdx",
                **meta,
                "src_lic": ext_coll["license"],
                "src_url": HDX_SRC_URL,
                "via_extended": f"{SC_URL}/extended/{layer}",
                "via_original": f"{SC_URL}/original/{layer}",
            }
        )
    return rows


def _data_asset(coll: dict, base: str) -> tuple[str, int | None]:
    """Return the URL and byte size of a STAC collection's data asset."""
    asset = next(a for a in coll["assets"].values() if "data" in a.get("roles", []))
    return f"{base}/{asset['href'].removeprefix('./')}", asset.get("file:size")


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


def _load_extended(  # noqa: PLR0913
    conn: duckdb.DuckDBPyConnection,
    raw: Path,
    *,
    iso3: str,
    lvl: int,
    meta: dict,
    lic: str,
) -> None:
    """Map one COD extended layer into the `admin` table and rebuild its IDs."""
    conn.execute(ADMIN_SCHEMA_SQL)
    pcode_select = ", ".join(
        f"adm{n}_pcode AS adm{n}_id, adm{n}_pcode AS adm{n}_src, "
        f"adm{n}_name, adm{n}_name1, adm{n}_name2"
        for n in range(lvl + 1)
    )
    conn.execute(
        f"""--sql
        INSERT INTO admin BY NAME
        SELECT '{iso3}' AS iso3,
               {pcode_select},
               ? AS src_lvl,
               lang AS src_lang, lang1 AS src_lang1, lang2 AS src_lang2,
               CAST(valid_on AS DATE) AS src_date,
               CAST(valid_to AS DATE) AS src_update,
               ? AS src_name, ? AS src_name1, ? AS src_lic,
               '{HDX_SRC_URL}' AS src_url,
               'COD' AS src_grp,
               geometry AS geom
        FROM read_parquet('{raw}')
    """,
        [lvl, meta["src_name"], meta["src_name1"], lic],
    )
    conn.execute(id_gen_ctas_sql())
