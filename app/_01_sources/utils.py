"""Shared HTTP, schema, and output helpers for the sources stage."""

from pathlib import Path

import duckdb
import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import CATALOG_DIR, HTTP_TIMEOUT, PARQUET_OPTS

from .config import DOWNLOAD_CHUNK_SIZE, HTTP_CONNECT_TIMEOUT, MAX_LVL

ADMIN_SCHEMA_SQL = """--sql
CREATE OR REPLACE TABLE admin (
    iso3 VARCHAR,
    adm0_id VARCHAR, adm0_src VARCHAR,
    adm0_name VARCHAR, adm0_name1 VARCHAR, adm0_name2 VARCHAR,
    adm1_id VARCHAR, adm1_src VARCHAR,
    adm1_name VARCHAR, adm1_name1 VARCHAR, adm1_name2 VARCHAR,
    adm2_id VARCHAR, adm2_src VARCHAR,
    adm2_name VARCHAR, adm2_name1 VARCHAR, adm2_name2 VARCHAR,
    adm3_id VARCHAR, adm3_src VARCHAR,
    adm3_name VARCHAR, adm3_name1 VARCHAR, adm3_name2 VARCHAR,
    adm4_id VARCHAR, adm4_src VARCHAR,
    adm4_name VARCHAR, adm4_name1 VARCHAR, adm4_name2 VARCHAR,
    src_lvl INTEGER,
    src_lang VARCHAR, src_lang1 VARCHAR, src_lang2 VARCHAR,
    src_date DATE, src_update DATE,
    src_name VARCHAR, src_name1 VARCHAR, src_lic VARCHAR, src_url VARCHAR,
    src_grp VARCHAR,
    geom GEOMETRY
)
"""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.is_server_error


_retry = retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=2, max=60),
    reraise=True,
)


def _client() -> httpx.Client:
    return httpx.Client(
        http2=True,
        follow_redirects=True,
        timeout=httpx.Timeout(HTTP_TIMEOUT, connect=HTTP_CONNECT_TIMEOUT),
    )


@_retry
def get_json(url: str) -> dict | list:
    """GET url and return its JSON body."""
    with _client() as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


@_retry
def download(url: str, dest: Path, size: int | None = None) -> Path:
    """Stream url to dest, skipping when dest already has the remote size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _client() as client:
        if size is None:
            head = client.head(url)
            head.raise_for_status()
            size = int(head.headers.get("content-length", -1))
        if dest.exists() and dest.stat().st_size == size:
            return dest
        part = dest.with_name(dest.name + ".part")
        with client.stream("GET", url) as r:
            r.raise_for_status()
            with part.open("wb") as f:
                f.writelines(r.iter_bytes(chunk_size=DOWNLOAD_CHUNK_SIZE))
    part.replace(dest)
    return dest


def catalog_path(tier: str, key: str) -> Path:
    """Return catalog/{tier}/{key}/{key}_{tier}.parquet, creating its folder."""
    path = CATALOG_DIR / tier / key / f"{key}_{tier}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_extended(conn: duckdb.DuckDBPyConnection, key: str) -> Path:
    """Write the `admin` table to catalog/extended/{key}/, clamped to lon/lat range."""
    dest = catalog_path("extended", key)
    conn.execute(f"""--sql
        COPY (
            SELECT * EXCLUDE (geom), geom AS geometry FROM (
                SELECT * REPLACE (
                    CASE WHEN ST_XMin(geom) < -180 OR ST_XMax(geom) > 180
                           OR ST_YMin(geom) < -90 OR ST_YMax(geom) > 90
                    THEN ST_CollectionExtract(ST_Intersection(
                        geom, ST_MakeEnvelope(-180, -90, 180, 90)), 3)
                    ELSE geom END AS geom
                )
                FROM admin
            )
            WHERE NOT ST_IsEmpty(geom)
        ) TO '{dest}' {PARQUET_OPTS}
    """)
    return dest


def id_gen_ctas_sql() -> str:
    """Rewrite adm{0..4}_id hierarchically: adm0 = ISO3-YYYYMMDD, adm{N} = parent-seq.

    Rows where adm{N}_src is NULL keep adm{N}_id NULL.
    """
    ctes: list[str] = [
        """--sql
        adm0_done AS (
            SELECT * REPLACE (
                CASE WHEN src_date IS NULL THEN iso3
                     ELSE iso3 || '-' || strftime(src_date, '%Y%m%d')
                END AS adm0_id
            )
            FROM admin
        )
        """,
    ]
    for lvl in range(1, MAX_LVL + 1):
        parents = ", ".join(f"adm{n}_id" for n in range(lvl))
        ctes.append(f"""--sql
        adm{lvl}_ranked AS (
            SELECT *,
                DENSE_RANK() OVER (
                    PARTITION BY iso3, {parents}
                    ORDER BY adm{lvl}_src
                ) AS seq{lvl}
            FROM adm{lvl - 1}_done
        ),
        adm{lvl}_widths AS (
            SELECT iso3,
                CAST(LENGTH(CAST(MAX(seq{lvl}) AS VARCHAR)) AS INTEGER) AS pad{lvl}
            FROM adm{lvl}_ranked
            WHERE adm{lvl}_src IS NOT NULL
            GROUP BY iso3
        ),
        adm{lvl}_done AS (
            SELECT * EXCLUDE (seq{lvl}, pad{lvl})
                   REPLACE (
                       CASE WHEN adm{lvl}_src IS NULL THEN NULL
                            ELSE adm{lvl - 1}_id || '-'
                                 || LPAD(CAST(seq{lvl} AS VARCHAR), pad{lvl}, '0')
                       END AS adm{lvl}_id
                   )
            FROM adm{lvl}_ranked
            LEFT JOIN adm{lvl}_widths USING (iso3)
        )
        """)
    return (
        "CREATE OR REPLACE TABLE admin AS WITH "
        + ",".join(ctes)
        + f" SELECT * FROM adm{MAX_LVL}_done"
    )
