"""Ingest a EuroGeographics EBM product (ERM, EGM) release into catalog/source/."""

import re
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from datetime import date
from logging import getLogger
from pathlib import Path
from typing import NamedTuple

import duckdb
from topo_tools.api import edge_extend

from app._01_sources._01b_publish import publish
from app._01_sources.config import DOWNLOAD_DIR
from app._01_sources.schema import (
    LATIN,
    conform,
    conform_extended,
    split_extended,
    write_meta,
)
from app._01_sources.utils import catalog_path, drop_stale, meta_path, published_src
from app.adm0 import ADM0_HUMANITARIAN, adm0_path
from app.config import MAX_LVL, PARQUET_OPTS, PARTS
from app.publish.utils import portolan
from app.utils import get_conn

logger = getLogger(__name__)

# ISO 639-2/B to the ISO 639-1 codes cod-ab uses; others keep their 3 letters.
LANGS = {
    "alb": "sq", "baq": "eu", "bos": "bs", "cat": "ca", "cze": "cs",
    "dan": "da", "dut": "nl", "eng": "en", "est": "et", "fao": "fo",
    "fin": "fi", "fre": "fr", "fry": "fy", "geo": "ka", "ger": "de",
    "gla": "gd", "gle": "ga", "gre": "el", "hrv": "hr", "ice": "is",
    "ita": "it", "kal": "kl", "lav": "lv", "lit": "lt", "mkd": "mk",
    "mlt": "mt", "nor": "no", "pol": "pl", "por": "pt", "roh": "rm",
    "rum": "ro", "slo": "sk", "slv": "sl", "spa": "es", "srp": "sr",
    "swe": "sv", "ukr": "uk", "val": "ca", "wel": "cy",
}  # fmt: skip


class Product(NamedTuple):
    """One EBM product: its source metadata and how its PolbndA maps to levels."""

    src: str
    src_url: str
    src_lic: str
    src_grp: str
    gpkg: str
    shn: int
    taa_keep: tuple[int, ...]
    taa_coastal: int
    skip: dict[str, set[int]]
    merge: dict[str, str]
    split: dict[str, dict[str, tuple[str, str]]]
    extra: dict[str, tuple[str, str]]
    agencies: Callable[[Path, list[str]], tuple[list[str], list[date]]]
    adopt: set[str]
    clean_original: bool


class Layer(NamedTuple):
    """One output layer: ERM ICC or SPLIT iso2, iso3, adm0 names, languages, date."""

    icc: str
    iso3: str
    adm0: tuple
    langs: list
    valid_from: date | None


def run(product: Product, doc: str) -> None:
    """Rewrite catalog/source/{base}/ for every country published from product."""
    parser = ArgumentParser(description=doc)
    parser.add_argument("root", type=Path)
    parser.add_argument("--icc", type=lambda v: set(v.split(",")), default=None)
    parser.add_argument("--skip-publish", action="store_true")
    args = parser.parse_args()
    work = DOWNLOAD_DIR / product.src
    work.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    _load(conn, product, args.root)
    iso3 = dict(
        conn.execute(
            "SELECT DISTINCT iso2, iso3 FROM read_parquet(?)",
            [adm0_path(ADM0_HUMANITARIAN)],
        ).fetchall()
    )
    countries = [
        r[0] for r in conn.execute("SELECT DISTINCT cc FROM k ORDER BY cc").fetchall()
    ]
    for cc in countries:
        if args.icc is None or cc in args.icc:
            _select(conn, product, args, cc, iso3)
    conn.close()
    if not args.skip_publish:
        publish()


def _select(
    conn: duckdb.DuckDBPyConnection,
    product: Product,
    args: Namespace,
    cc: str,
    iso3: dict[str, str],
) -> None:
    """Write cc if published from product or adopted via --icc, else log why not."""
    named = args.icc is not None
    keys = [iso3[cc].lower()] + [
        iso3[icc].lower() for icc, _ in product.split.get(cc, {}).values()
    ]
    src = published_src(keys[0])
    adoptable = src is None or src in product.adopt
    if src == product.src:
        _country(conn, product, args.root, cc, iso3)
    elif named and adoptable:
        if not _orders(conn, product, cc):
            logger.info("%s: no subnational orders, keeping %s", cc, src)
            return
        for key in keys:
            if (other := published_src(key)) in product.adopt:
                logger.info(
                    "%s: replacing %s (units per level %s) with %s",
                    key, other, _published_counts(conn, key), product.src,
                )  # fmt: skip
                portolan("rm", "-f", f"source/{key}")
        _country(conn, product, args.root, cc, iso3)
    elif named:
        logger.info("%s: published from %s, skipping", cc, src)
    elif adoptable and _orders(conn, product, cc):
        logger.info(
            "%s: adoption candidate over %s (units per level %s), pass --icc %s",
            cc, src, _published_counts(conn, keys[0]), cc,
        )  # fmt: skip


def _load(conn: duckdb.DuckDBPyConnection, product: Product, root: Path) -> None:
    """Load the kept PolbndA pieces as `k` and split EBM_NAM names as `nam`."""
    found = sorted(root.glob(product.gpkg))
    if len(found) != 1:
        msg = f"{root}: expected one {product.gpkg}, found {[str(f) for f in found]}"
        raise FileNotFoundError(msg)
    gpkg = found[0]
    merge = " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in product.merge.items())
    langs = " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in LANGS.items())
    polys = ["PolbndA", *(p for p, _ in product.extra.values())]
    names = ["EBM_NAM", *(n for _, n in product.extra.values())]
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE pa AS
        {
        " UNION ALL BY NAME ".join(
            f"SELECT * FROM ST_Read('{gpkg}', layer = '{p}')" for p in polys
        )
    }
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE k AS
        SELECT *, CASE ICC {merge} ELSE ICC END AS cc
        FROM pa
        WHERE TAA IN ({", ".join(map(str, product.taa_keep))})
          AND ICC NOT LIKE '%#%' AND ICC <> 'XX'
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE nam AS
        SELECT
            SHN AS code,
            ICC AS icc,
            string_split(NAMN, '#') AS names,
            list_transform(string_split(NLN, '#'), lambda x:
                CASE x {langs} WHEN 'UNK' THEN NULL ELSE x END) AS langs,
            NULLIF(left(effectiveDate::VARCHAR, 10), '1900-01-01')::DATE AS valid_from
        FROM ({
        " UNION ALL BY NAME ".join(
            f"SELECT * FROM ST_Read('{gpkg}', layer = '{n}')" for n in names
        )
    })
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE cc_names AS
        SELECT EuroGeographics_Country_Code AS icc, name_english_short, name_national
        FROM ST_Read('{gpkg}', layer = 'CountryCodes')
    """)


def _orders(conn: duckdb.DuckDBPyConnection, product: Product, cc: str) -> list[int]:
    """Return the USE orders of cc that hold codes and that SKIP keeps."""
    uses = range(2, product.shn + 2)
    present = conn.execute(
        "SELECT "
        + ", ".join(f"bool_or(SHN{u - 1} <> 'UNK')" for u in uses)
        + " FROM k WHERE cc = ?",
        [cc],
    ).fetchall()[0]
    return [
        u
        for u, has in zip(uses, present, strict=True)
        if has and u not in product.skip.get(cc, set())
    ]


def _ext_keys(key: str) -> list[str]:
    """Return the extended-tier keys of key: one per PARTS clip part, else key."""
    return [p.lower() for p in PARTS.get(key, ())] or [key]


def _country(
    conn: duckdb.DuckDBPyConnection,
    product: Product,
    root: Path,
    cc: str,
    iso3: dict[str, str],
) -> None:
    """Write original and extended layers plus metadata for cc and its SPLIT parts."""
    work = DOWNLOAD_DIR / product.src
    orders = _orders(conn, product, cc)
    lvl = len(orders)
    if lvl == 0:
        logger.info("%s: no subnational orders, skipping", cc)
        return
    if lvl > MAX_LVL:
        msg = f"{cc}: {lvl} orders {orders} exceed {MAX_LVL}; add a SKIP entry"
        raise ValueError(msg)
    _pieces(conn, product, cc, orders)
    _check(conn, cc, lvl)
    adm0 = conn.execute(
        "SELECT name_english_short, name_national FROM cc_names WHERE icc = ?", [cc]
    ).fetchall()
    split = product.split.get(cc, {})
    layers = [
        (
            cc,
            adm0[0] if adm0 else (None, None),
            "NOT list_contains(?::VARCHAR[], c1)",
            [*split],
        )
    ]
    layers += [
        (icc, (name, None), "c1 = ?", code) for code, (icc, name) in split.items()
    ]
    for icc, names, where, arg in layers:
        conn.execute(
            f"CREATE OR REPLACE TABLE pt AS SELECT * FROM p WHERE {where}", [arg]
        )
        layer = Layer(icc, iso3[icc], names, *_names(conn, lvl))
        key = layer.iso3.lower()
        published = _published_counts(conn, key)
        drop_stale(key, {("original", key)} | {("extended", k) for k in _ext_keys(key)})
        _write_extended(conn, layer, lvl, work)
        raw = work / f"{icc}.parquet"
        _write_original(raw, layer.iso3.lower(), lvl, clean=product.clean_original)
        counts = conn.execute(
            "SELECT "
            + ", ".join(f"count(DISTINCT c{i})" for i in range(1, lvl + 1))
            + " FROM pt"
        ).fetchall()[0]
        logger.info(
            "%s: orders %s, units per level %s (published %s), langs %s",
            icc, orders, counts, published, layer.langs,
        )  # fmt: skip
        _write_meta(product, root, cc, layer, lvl)


def _published_counts(conn: duckdb.DuckDBPyConnection, key: str) -> tuple:
    """Return the distinct pcodes per level of key's published original, () if none."""
    path = catalog_path("original", key)
    if not path.exists():
        return ()
    cols = [r[0] for r in conn.execute(f"DESCRIBE FROM '{path}'").fetchall()]
    lvls = sorted(int(c[3]) for c in cols if re.fullmatch(r"adm[1-9]_pcode", c))
    if not lvls:
        return ()
    counts = ", ".join(f"count(DISTINCT adm{i}_pcode)" for i in lvls)
    return conn.execute(f"SELECT {counts} FROM '{path}'").fetchall()[0]


def _names(conn: duckdb.DuckDBPyConnection, lvl: int) -> tuple[list, date | None]:
    """Build `un`, one name per layer language for every unit in `pt`, and the date.

    Languages rank by units named in them (max 4); the first falls back to a Latin name.
    """
    codes = " UNION ".join(f"SELECT c{i} FROM pt" for i in range(1, lvl + 1))
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE un_pairs AS
        SELECT code, i, names[i] AS name, langs[i] AS lang
        FROM (
            SELECT code, names, langs, unnest(generate_series(1, len(names))) AS i
            FROM nam WHERE code IN ({codes})
        )
    """)
    langs, valid_from = conn.execute(f"""--sql
        SELECT
            (SELECT list(lang ORDER BY n DESC, lang)[1:4] FROM (
                SELECT lang, count(DISTINCT code) AS n FROM un_pairs
                WHERE lang IS NOT NULL GROUP BY lang
            )),
            (SELECT max(valid_from) FROM nam WHERE code IN ({codes}))
    """).fetchall()[0]
    langs = [*(langs or []), None, None, None, None][:4]
    first = "min_by(name, i) FILTER (lang = ${})"
    conn.execute(
        f"""--sql
        CREATE OR REPLACE TABLE un AS
        SELECT code,
            coalesce(
                {first.format(1)},
                min_by(name, i) FILTER (regexp_full_match(name, '{LATIN}'))
            ) AS n0,
            {first.format(2)} AS n1, {first.format(3)} AS n2, {first.format(4)} AS n3
        FROM un_pairs GROUP BY code
    """,
        langs,
    )
    return langs, valid_from


def _pieces(
    conn: duckdb.DuckDBPyConnection, product: Product, cc: str, orders: list[int]
) -> None:
    """Build table `p` of pieces with codes c0..c{lvl}, gaps filled from the parent.

    Land gaps join the longest-border sibling, else the nearest; water needs leaf codes.
    """
    lvl = len(orders)
    coastal = product.taa_coastal
    raw = ", ".join(
        f"NULLIF(SHN{u - 1}, 'UNK') AS c{i}" for i, u in enumerate(orders, 1)
    )
    conn.execute(
        f"""--sql
        CREATE OR REPLACE TABLE p AS
        SELECT row_number() OVER () AS pid, NULLIF(SHN0, 'UNK') AS c0, {raw}, geom
        FROM k WHERE cc = ? AND TAA <> {coastal}
    """,
        [cc],
    )
    conn.execute(
        f"""--sql
        CREATE OR REPLACE TABLE p5 AS
        SELECT NULLIF(SHN{orders[-1] - 1}, 'UNK') AS c{lvl}, geom
        FROM k WHERE cc = ? AND TAA = {coastal}
    """,
        [cc],
    )
    for i in range(1, lvl + 1):
        conn.execute(f"""--sql
            UPDATE p SET c{i} = c{i - 1}
            WHERE c{i} IS NULL AND c{i - 1} NOT IN (
                SELECT c{i - 1} FROM p WHERE c{i} IS NOT NULL
            )
        """)
        deeper = ", ".join(f"c{j} = n.c{j}" for j in range(i, lvl + 1))
        conn.execute(f"""--sql
            UPDATE p SET {deeper}
            FROM (
                SELECT f.pid, arg_max(
                    n.pid, ST_Length(ST_Intersection(f.geom, n.geom))
                ) AS nid
                FROM p f JOIN p n
                  ON f.c{i} IS NULL AND n.c{i} IS NOT NULL
                 AND f.c{i - 1} = n.c{i - 1} AND ST_Intersects(f.geom, n.geom)
                GROUP BY f.pid
            ) AS a, p AS n
            WHERE p.pid = a.pid AND n.pid = a.nid
        """)
        conn.execute(f"""--sql
            UPDATE p SET {deeper}
            FROM (
                SELECT f.pid, arg_min(n.pid, ST_Distance(f.geom, n.geom)) AS nid
                FROM p f JOIN p n
                  ON f.c{i} IS NULL AND n.c{i} IS NOT NULL
                 AND f.c{i - 1} = n.c{i - 1}
                GROUP BY f.pid
            ) AS a, p AS n
            WHERE p.pid = a.pid AND n.pid = a.nid
        """)
        dropped = conn.execute(
            f"DELETE FROM p WHERE c{i} IS NULL RETURNING pid"
        ).fetchall()
        if dropped:
            logger.warning(
                "%s: dropped %d untouched level-%d fragments", cc, len(dropped), i
            )
    upper = ", ".join(f"u.c{j}" for j in range(lvl))
    kept = conn.execute(f"""--sql
        INSERT INTO p
        SELECT (SELECT max(pid) FROM p) + row_number() OVER (),
            {upper}, w.c{lvl}, w.geom
        FROM p5 w
        JOIN (SELECT DISTINCT {", ".join(f"c{j}" for j in range(lvl + 1))} FROM p) u
          ON u.c{lvl} = w.c{lvl}
    """).fetchall()[0][0]
    total = conn.execute("SELECT count(*) FROM p5").fetchall()[0][0]
    if total:
        logger.info("%s: kept %d of %d coastal water pieces", cc, kept, total)


def _check(conn: duckdb.DuckDBPyConnection, cc: str, lvl: int) -> None:
    """Raise unless every piece has a country code, nests cleanly, and has names."""
    if conn.execute("SELECT count(*) FROM p WHERE c0 IS NULL").fetchall()[0][0]:
        msg = f"{cc}: pieces with no country code"
        raise ValueError(msg)
    for i in range(1, lvl + 1):
        bad = conn.execute(
            f"SELECT c{i} FROM p GROUP BY c{i} "
            f"HAVING count(DISTINCT c{i - 1}) > 1 LIMIT 5"
        ).fetchall()
        if bad:
            msg = f"{cc}: level {i} units with several parents: {bad}"
            raise ValueError(msg)
    union = " UNION ".join(f"SELECT c{i} AS code FROM p" for i in range(1, lvl + 1))
    missing = conn.execute(
        f"SELECT code FROM ({union}) WHERE code NOT IN (SELECT code FROM nam) LIMIT 5"
    ).fetchall()
    if missing:
        msg = f"{cc}: codes with no EBM_NAM name: {missing}"
        raise ValueError(msg)


def _write_extended(
    conn: duckdb.DuckDBPyConnection, layer: Layer, lvl: int, work: Path
) -> None:
    """Dissolve `pt` per leaf, reproject, extend with topo-tools, then conform."""
    group = ", ".join(f"c{i}" for i in range(1, lvl + 1))
    levels = ", ".join(
        f"n{i}.n0 AS adm{i}_name, n{i}.n1 AS adm{i}_name1, "
        f"n{i}.n2 AS adm{i}_name2, n{i}.n3 AS adm{i}_name3, "
        f"d.c{i} AS adm{i}_pcode"
        for i in range(1, lvl + 1)
    )
    joins = " ".join(f"JOIN un n{i} ON n{i}.code = d.c{i}" for i in range(1, lvl + 1))
    raw = work / f"{layer.icc}.parquet"
    conn.execute(
        f"""--sql
        COPY (
            WITH d AS (
                SELECT {group}, ST_Transform(
                    ST_MakeValid(ST_Union_Agg(geom)), 'EPSG:4258', 'EPSG:4326', true
                ) AS geom
                FROM pt
                GROUP BY {group}
            )
            SELECT {levels},
                ?::VARCHAR AS adm0_name, ?::VARCHAR AS adm0_name1, ? AS adm0_pcode,
                ?::VARCHAR AS lang, ?::VARCHAR AS lang1,
                ?::VARCHAR AS lang2, ?::VARCHAR AS lang3,
                ?::DATE AS valid_from,
                ? AS iso2, ? AS iso3, d.geom AS geometry
            FROM d {joins}
        ) TO '{raw}' {PARQUET_OPTS}
    """,
        [*layer.adm0, layer.icc, *layer.langs, layer.valid_from, layer.icc, layer.iso3],
    )
    keys = _ext_keys(layer.iso3.lower())
    if len(keys) > 1:
        original = f"SELECT * FROM read_parquet('{raw}')"
        split_extended(conn, original, lvl, PARTS[layer.iso3.lower()], work / "split")
        return
    extended = work / f"{layer.icc}_extended.parquet"
    edge_extend(raw, extended)
    conform_extended(
        conn,
        f"SELECT * FROM read_parquet('{extended}')",
        lvl,
        catalog_path("extended", keys[0]),
    )


def _write_original(raw: Path, key: str, lvl: int, *, clean: bool) -> None:
    """Write the dissolved, unextended layer in the extended schema as `original`."""
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        write = conform_extended if clean else conform
        write(
            conn,
            f"SELECT * FROM read_parquet('{raw}')",
            lvl,
            catalog_path("original", key),
        )


def _write_meta(product: Product, root: Path, cc: str, layer: Layer, lvl: int) -> None:
    """Write both tiers' metadata rows, naming each ICC's mapping agency."""
    iccs = [cc, *(a for a, b in product.merge.items() if b == cc)]
    agencies, stamps = product.agencies(root, iccs)
    row = {
        "key": layer.iso3.lower(),
        "iso3": layer.iso3,
        "src": product.src,
        "src_lvl": lvl,
        "src_lang": layer.langs[0],
        "src_lang1": layer.langs[1],
        "src_lang2": layer.langs[2],
        "src_date": layer.valid_from,
        "src_update": max(stamps, default=None),
        "src_name": "; ".join(agencies) or None,
        "src_name1": "EuroGeographics",
        "src_lic": product.src_lic,
        "src_url": product.src_url,
        "src_grp": product.src_grp,
        "via": product.src_url,
    }
    path = meta_path(row["key"])
    write_meta({**row, "tier": "original"}, path)
    for key in _ext_keys(row["key"]):
        write_meta({**row, "key": key, "tier": "extended"}, path)
