"""Ingest a EuroGeographics EuroRegionalMap (ERM) release into catalog/iso3/.

Run: uv run python -m scripts.ingest_erm ~/Downloads/FullEurope [--icc DE,FR]
"""

import re
from argparse import ArgumentParser
from datetime import date
from logging import getLogger
from pathlib import Path

import duckdb
from topo_tools.api import edge_extend

from app._01_sources._01b_publish import publish
from app._01_sources.config import DOWNLOAD_DIR
from app._01_sources.schema import conform, conform_extended, write_meta
from app._01_sources.utils import catalog_path, meta_path, published_src
from app._02_build._02a_inputs import adm0_path
from app._02_build.config import ADM0_HUMANITARIAN
from app.config import MAX_LVL, PARQUET_OPTS
from app.utils import get_conn

logger = getLogger(__name__)

SRC = "erm"
WORK_DIR = DOWNLOAD_DIR / SRC
SRC_URL = "https://www.mapsforeurope.org/datasets/euro-regional-map"
SRC_LIC = "EuroGeographics Open Data Licence 2024"
# Kept area types: 1 main, 3 branch, 4 special, 5 coastal water, 7 inland water.
TAA_KEEP = (1, 3, 4, 5, 7)
TAA_COASTAL = 5
# ERM ICC folded into another country's layer.
MERGE = {"ND": "GB"}
# ERM orders (USE 2..6) left out, matching Mapbox Boundaries v4.7 levels.
SKIP = {
    "DE": {3, 5},
    "FR": {5},
    "GF": {5},
    "GP": {5},
    "MQ": {5},
    "RE": {5},
    "YT": {5},
    "GB": {5},
    "CY": {4},
    "FI": {2, 4},
    "IE": {2},
    "PT": {2},
}
# ISO 639-2/B to the ISO 639-1 codes cod-ab uses; others keep their 3 letters.
LANGS = {
    "alb": "sq", "baq": "eu", "cat": "ca", "cze": "cs", "dan": "da",
    "dut": "nl", "eng": "en", "est": "et", "fao": "fo", "fin": "fi",
    "fre": "fr", "fry": "fy", "geo": "ka", "ger": "de", "gla": "gd",
    "gle": "ga", "gre": "el", "hrv": "hr", "ice": "is", "ita": "it",
    "lav": "lv", "lit": "lt", "mkd": "mk", "mlt": "mt", "nor": "no",
    "pol": "pl", "por": "pt", "roh": "rm", "rum": "ro", "slo": "sk",
    "slv": "sl", "spa": "es", "swe": "sv", "ukr": "uk", "val": "ca",
}  # fmt: skip
_ORG = re.compile(r"<gmd:organisationName>\s*<gco:CharacterString>([^<]+)")
_STAMP = re.compile(r"<gmd:dateStamp>\s*<gco:Date>([^<]+)")


def main() -> None:
    """Rewrite catalog/iso3/{iso3}/ for every ERM country published from erm."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--icc", type=lambda v: set(v.split(",")), default=None)
    parser.add_argument("--skip-publish", action="store_true")
    args = parser.parse_args()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    _load(conn, args.root)
    iso3 = dict(
        conn.execute(
            "SELECT DISTINCT iso_2, iso_3 FROM read_parquet(?)",
            [adm0_path(ADM0_HUMANITARIAN)],
        ).fetchall()
    )
    countries = [
        r[0] for r in conn.execute("SELECT DISTINCT cc FROM k ORDER BY cc").fetchall()
    ]
    for cc in countries:
        published = published_src(iso3[cc].lower()) == SRC
        if published and (args.icc is None or cc in args.icc):
            _country(conn, args.root, cc, iso3[cc])
    conn.close()
    if not args.skip_publish:
        publish()


def _load(conn: duckdb.DuckDBPyConnection, root: Path) -> None:
    """Load the kept PolbndA pieces as `k` and split EBM_NAM names as `nam`."""
    gpkg = root / "data" / "FullEurope" / "FullEurope.gpkg"
    merge = " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in MERGE.items())
    langs = " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in LANGS.items())
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE pa AS
        SELECT * FROM ST_Read('{gpkg}', layer = 'PolbndA')
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE k AS
        SELECT *, CASE ICC {merge} ELSE ICC END AS cc
        FROM pa
        WHERE TAA IN {TAA_KEEP} AND ICC NOT LIKE '%#%' AND ICC <> 'XX'
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE nam AS
        SELECT
            SHN AS code,
            ICC AS icc,
            string_split(NAMN, '#') AS names,
            list_transform(string_split(NLN, '#'), lambda x:
                CASE x {langs} WHEN 'UNK' THEN NULL ELSE x END) AS langs,
            NULLIF(left(effectiveDate::VARCHAR, 10), '1900-01-01')::DATE AS valid_on
        FROM ST_Read('{gpkg}', layer = 'EBM_NAM')
    """)
    conn.execute(f"""--sql
        CREATE OR REPLACE TABLE cc_names AS
        SELECT EuroGeographics_Country_Code AS icc, name_english_short, name_national
        FROM ST_Read('{gpkg}', layer = 'CountryCodes')
    """)


def _country(conn: duckdb.DuckDBPyConnection, root: Path, cc: str, iso3: str) -> None:
    """Write one country's original and extended layers plus metadata."""
    key = iso3.lower()
    present = conn.execute(
        "SELECT "
        + ", ".join(f"bool_or(SHN{u - 1} <> 'UNK')" for u in range(2, 7))
        + " FROM k WHERE cc = ?",
        [cc],
    ).fetchall()[0]
    orders = [
        u
        for u, has in zip(range(2, 7), present, strict=True)
        if has and u not in SKIP.get(cc, set())
    ]
    lvl = len(orders)
    if lvl == 0:
        logger.info("%s: no subnational orders, skipping", cc)
        return
    if lvl > MAX_LVL:
        msg = f"{cc}: {lvl} orders {orders} exceed {MAX_LVL}; add a SKIP entry"
        raise ValueError(msg)
    _pieces(conn, cc, orders)
    _check(conn, cc, lvl)
    _write_extended(conn, cc, iso3, lvl)
    _write_original(cc, key, lvl)
    counts = conn.execute(
        "SELECT "
        + ", ".join(f"count(DISTINCT c{i})" for i in range(1, lvl + 1))
        + " FROM p"
    ).fetchall()[0]
    logger.info("%s: orders %s, units per level %s", cc, orders, counts)
    _write_meta(conn, root, cc, iso3, lvl)


def _pieces(conn: duckdb.DuckDBPyConnection, cc: str, orders: list[int]) -> None:
    """Build table `p` of pieces with codes c0..c{lvl}, gaps filled from the parent.

    Land gaps join the longest-border sibling, else the nearest; water needs leaf codes.
    """
    lvl = len(orders)
    raw = ", ".join(
        f"NULLIF(SHN{u - 1}, 'UNK') AS c{i}" for i, u in enumerate(orders, 1)
    )
    conn.execute(
        f"""--sql
        CREATE OR REPLACE TABLE p AS
        SELECT row_number() OVER () AS pid, NULLIF(SHN0, 'UNK') AS c0, {raw}, geom
        FROM k WHERE cc = ? AND TAA <> {TAA_COASTAL}
    """,
        [cc],
    )
    conn.execute(
        f"""--sql
        CREATE OR REPLACE TABLE p5 AS
        SELECT NULLIF(SHN{orders[-1] - 1}, 'UNK') AS c{lvl}, geom
        FROM k WHERE cc = ? AND TAA = {TAA_COASTAL}
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
    conn: duckdb.DuckDBPyConnection, cc: str, iso3: str, lvl: int
) -> None:
    """Dissolve pieces per leaf, reproject, extend with topo-tools, then conform."""
    group = ", ".join(f"c{i}" for i in range(1, lvl + 1))
    levels = ", ".join(
        f"n{i}.names[1] AS adm{i}_name, n{i}.names[2] AS adm{i}_name1, "
        f"n{i}.names[3] AS adm{i}_name2, n{i}.names[4] AS adm{i}_name3, "
        f"d.c{i} AS adm{i}_pcode"
        for i in range(1, lvl + 1)
    )
    joins = " ".join(f"JOIN nam n{i} ON n{i}.code = d.c{i}" for i in range(1, lvl + 1))
    raw = WORK_DIR / f"{cc}.parquet"
    conn.execute(
        f"""--sql
        COPY (
            WITH d AS (
                SELECT {group}, ST_Transform(
                    ST_MakeValid(ST_Union_Agg(geom)), 'EPSG:4258', 'EPSG:4326', true
                ) AS geom
                FROM p
                GROUP BY {group}
            )
            SELECT {levels},
                c.name_english_short AS adm0_name, c.name_national AS adm0_name1,
                ? AS adm0_pcode,
                n{lvl}.langs[1] AS lang, n{lvl}.langs[2] AS lang1,
                n{lvl}.langs[3] AS lang2, n{lvl}.langs[4] AS lang3,
                n{lvl}.valid_on,
                ? AS iso2, ? AS iso3, d.geom AS geometry
            FROM d {joins}
            LEFT JOIN cc_names c ON c.icc = ?
        ) TO '{raw}' {PARQUET_OPTS}
    """,
        [cc, cc, iso3, cc],
    )
    extended = WORK_DIR / f"{cc}_extended.parquet"
    edge_extend(raw, extended)
    conform_extended(
        conn,
        f"SELECT * FROM read_parquet('{extended}')",
        lvl,
        catalog_path("extended", iso3.lower()),
    )


def _write_original(cc: str, key: str, lvl: int) -> None:
    """Write the dissolved, unextended layer in the extended schema as `original`."""
    with duckdb.connect() as conn:
        conn.execute("LOAD spatial")
        conform(
            conn,
            f"SELECT * FROM read_parquet('{WORK_DIR / f'{cc}.parquet'}')",
            lvl,
            catalog_path("original", key),
        )


def _write_meta(
    conn: duckdb.DuckDBPyConnection, root: Path, cc: str, iso3: str, lvl: int
) -> None:
    """Write both tiers' metadata rows, naming each ICC's mapping agency."""
    iccs = [cc, *(a for a, b in MERGE.items() if b == cc)]
    agencies, stamps = [], []
    for icc in iccs:
        xml = next((root / "Metadata" / "Countries").glob(f"{icc}_ERM_*_Metadata.xml"))
        text = xml.read_text(encoding="utf-8")
        if org := _ORG.search(text):
            agencies.append(org[1].strip())
        if stamp := _STAMP.search(text):
            stamps.append(date.fromisoformat(stamp[1].strip()[:10]))
    langs, src_date = conn.execute(
        """--sql
        SELECT
            (SELECT list(l ORDER BY n DESC) FROM (
                SELECT langs[1] AS l, count(*) AS n FROM nam
                WHERE list_contains($1, icc) AND langs[1] IS NOT NULL
                GROUP BY l
            )),
            (SELECT max(valid_on) FROM nam WHERE list_contains($1, icc))
    """,
        [iccs],
    ).fetchall()[0]
    langs = (langs or []) + [None, None, None]
    row = {
        "key": iso3.lower(),
        "iso3": iso3,
        "src": SRC,
        "src_lvl": lvl,
        "src_lang": langs[0],
        "src_lang1": langs[1],
        "src_lang2": langs[2],
        "src_date": src_date,
        "src_update": max(stamps, default=None),
        "src_name": "; ".join(agencies) or None,
        "src_name1": "EuroGeographics",
        "src_lic": SRC_LIC,
        "src_url": SRC_URL,
        "src_grp": "ERM",
        "via": SRC_URL,
    }
    for tier in ("extended", "original"):
        write_meta({**row, "tier": tier}, meta_path(iso3.lower()))


if __name__ == "__main__":
    main()
