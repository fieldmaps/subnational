"""Shared utilities for the build stage."""

import duckdb

from app.config import MAX_LVL

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


def describe(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return the column names of a DuckDB table."""
    return [row[0] for row in conn.execute(f"DESCRIBE {table}").fetchall()]


def wld_cols() -> list[str]:
    """Return ordered list of world-view attribute column names."""
    return [
        "adm0_id",
        "adm0_src",
        "adm0_name",
        "adm0_name1",
        "adm0_name2",
        "iso_cd",
        "iso_2",
        "iso_3",
        "iso_3_grp",
        "region3_cd",
        "region3_nm",
        "region2_cd",
        "region2_nm",
        "region1_cd",
        "region1_nm",
        "status_cd",
        "status_nm",
        "wld_date",
        "wld_update",
        "wld_view",
        "wld_notes",
    ]


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
