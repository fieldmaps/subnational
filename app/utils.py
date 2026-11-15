"""Shared DuckDB connection, profiled per query when DEBUG is set."""

import contextlib
import re
import threading
import time
from logging import getLogger
from pathlib import Path
from typing import cast

import duckdb
import psutil
from duckdb import DuckDBPyConnection

import app.config
from app.config import CATALOG_DIR

logger = getLogger(__name__)


def get_conn(
    path: Path | None = None,
    *,
    reset: bool = False,
    read_only: bool = False,
    threads: int = 4,
) -> DuckDBPyConnection:
    """Open a DuckDB connection, loading spatial and httpfs.

    path=None → in-memory; path=Path → file at that location.
    reset=True deletes the file first (no-op for in-memory).
    Returns a ProfiledConnection (cast to DuckDBPyConnection) when DEBUG is enabled.
    """
    if path is None:
        conn = duckdb.connect()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            path.unlink(missing_ok=True)
        conn = duckdb.connect(str(path), read_only=read_only)
    conn.execute("LOAD spatial;")
    conn.execute("LOAD httpfs;")
    conn.execute("SET enable_progress_bar = false")
    conn.execute("SET geometry_always_xy = true")
    conn.execute("SET preserve_insertion_order = false")
    conn.execute(f"SET threads = {threads}")
    # DuckDB 2.0.0 drops rows from WHERE ST_*() on shredded CRS geometry.
    conn.execute("SET geometry_minimum_shredding_size = -1")
    if app.config.DEBUG:
        return cast("DuckDBPyConnection", ProfiledConnection(conn))
    return conn


def global_path(lvl: int, geom: str) -> Path:
    """Return catalog/global/adm{n}-{geom}/adm{n}_{geom}.parquet."""
    return CATALOG_DIR / "global" / f"adm{lvl}-{geom}" / f"adm{lvl}_{geom}.parquet"


_PROCESS = psutil.Process()
_MEM_Q = "SELECT COALESCE(SUM(memory_usage_bytes), 0) FROM duckdb_memory()"


class ProfiledConnection:
    """Proxy around DuckDBPyConnection; logs RSS peak and DuckDB delta per execute().

    RSS peak captures GEOS working memory that duckdb_memory() misses.
    """

    def __init__(self, conn: DuckDBPyConnection) -> None:  # noqa: D107
        self._conn = conn

    def execute(self, query: str, parameters: list | None = None):  # noqa: ANN201
        """Log wall-clock time, RSS peak, and DuckDB delta/total, then forward."""
        t0 = time.perf_counter()
        before_rss = _PROCESS.memory_info().rss
        before_ddb = self._conn.execute(_MEM_Q).fetchall()[0][0]

        peak_rss = [before_rss]
        stop = threading.Event()

        def _poll() -> None:
            while not stop.is_set():
                with contextlib.suppress(Exception):
                    peak_rss[0] = max(peak_rss[0], _PROCESS.memory_info().rss)
                stop.wait(0.05)

        threading.Thread(target=_poll, daemon=True).start()

        result = (
            self._conn.execute(query, parameters)
            if parameters is not None
            else self._conn.execute(query)
        )
        description = getattr(result, "description", None)
        rows = result.fetchall()

        stop.set()
        after_rss = _PROCESS.memory_info().rss
        peak_rss[0] = max(peak_rss[0], after_rss)
        after_ddb = self._conn.execute(_MEM_Q).fetchall()[0][0]

        elapsed = time.perf_counter() - t0
        logger.info(
            "query %.3fs | rss peak %.0f MB | duckdb %+.0f MB | %.0f MB total | %s",
            elapsed,
            peak_rss[0] / 1e6,
            (after_ddb - before_ddb) / 1e6,
            after_ddb / 1e6,
            _query_label(query),
        )
        return _EagerResult(rows, description)

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __getattr__(self, name: str) -> object:  # noqa: D105
        return getattr(self._conn, name)


class _EagerResult:
    """Materialised DuckDB result that survives subsequent execute() calls."""

    def __init__(self, rows: list, description: list | None = None) -> None:
        self._rows = rows
        self.description = description

    def fetchall(self) -> list:
        return self._rows


def _query_label(query: str) -> str:
    q = " ".join(query.split())
    m = re.search(r'CREATE (?:OR REPLACE )?TABLE "([^"]+)"', q, re.IGNORECASE)
    if m:
        return f"CREATE {m.group(1)}"
    m = re.search(r'DROP TABLE (?:IF EXISTS )?"([^"]+)"', q, re.IGNORECASE)
    if m:
        return f"DROP {m.group(1)}"
    m = re.search(r'ALTER TABLE "[^"]+" RENAME TO "([^"]+)"', q, re.IGNORECASE)
    if m:
        return f"RENAME TO {m.group(1)}"
    m = re.search(r"COPY .+? TO '([^']+)'", q, re.IGNORECASE)
    if m:
        return f"COPY {m.group(1)}"
    return q[:80]
