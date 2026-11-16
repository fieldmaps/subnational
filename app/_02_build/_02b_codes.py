"""Edge-mosaic, fill down and package each world-view iso3 code, in parallel."""

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import closing
from logging import WARNING, Handler, LogRecord, getLogger
from pathlib import Path
from shutil import rmtree

from topo_tools.api import edge_mosaic, package, schema_fill

from app._01_sources.utils import catalog_path, one_unit_bases
from app.config import PARQUET_OPTS
from app.utils import get_conn

from ._02a_inputs import PARENT, stage, staged_columns
from .config import (
    ADM0_FILL,
    BUILD_DIR,
    CODE_FIELD,
    ISO3,
    MATCH_KEY,
    NAME_FIELD,
    THREADS,
    WLD_COLS,
    WORKERS,
)

logger = getLogger(__name__)

CODES_DIR = BUILD_DIR / "iso3"


class _Unpaired(Handler):
    """Record topo-tools' warning that an input ran without its originals."""

    def __init__(self) -> None:
        super().__init__(WARNING)
        self.hit = False

    def emit(self, record: LogRecord) -> None:
        self.hit |= "runs without originals" in record.getMessage()


def build_codes(sources: dict[str, tuple]) -> None:
    """Package every iso3 code into CODES_DIR/{code}/, largest inputs first."""
    rmtree(CODES_DIR, ignore_errors=True)
    CODES_DIR.mkdir(parents=True)
    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"SELECT {ISO3}, list(DISTINCT lower({MATCH_KEY})) FROM '{PARENT}' "
            "GROUP BY ALL"
        ).fetchall()
        # A one-unit source adds no subdivision; its code is filled from ADM0.
        one_unit = one_unit_bases(conn)
    if unmatched := set(sources) - {k for _, keys in rows for k in keys}:
        msg = f"source keys with no parent row: {sorted(unmatched)}"
        raise ValueError(msg)
    codes = {
        code: {
            k: sources[k]
            for k in sorted(keys)
            if k in sources and k.split("_", maxsplit=1)[0] not in one_unit
        }
        for code, keys in rows
    }
    size = {
        code: sum(catalog_path("extended", k).stat().st_size for k in inputs)
        for code, inputs in codes.items()
    }
    pool = ProcessPoolExecutor(WORKERS)
    try:
        jobs = {
            pool.submit(_code_job, code, codes[code]): code
            for code in sorted(codes, key=lambda c: -size[c])
        }
        for done, job in enumerate(as_completed(jobs), 1):
            logger.info(
                "%s done in %.0fs (%d/%d)", jobs[job], job.result(), done, len(jobs)
            )
    finally:
        pool.shutdown(cancel_futures=True)


def _code_job(code: str, inputs: dict[str, tuple]) -> float:
    """Write CODES_DIR/{code}/admin{n}, points and lines from the code's parent rows."""
    t0 = time.perf_counter()
    work = CODES_DIR / code.lower()
    work.mkdir()
    parent, filled = work / "parent.parquet", work / "filled.parquet"
    with closing(get_conn(threads=THREADS)) as conn:
        conn.execute(
            f"COPY (SELECT * FROM '{PARENT}' WHERE {ISO3} = ?) "
            f"TO '{parent}' {PARQUET_OPTS}",
            [code],
        )
        staged = [work / f"{key}_staged.parquet" for key in inputs]
        for (key, meta), dest in zip(inputs.items(), staged, strict=True):
            stage(conn, key, meta, dest)
        if not inputs:
            _fill_rows(conn, parent, work / "rows.parquet")
    if inputs:
        _mosaic(code, work, staged, parent, filled)
    else:
        rows = work / "rows.parquet"
        schema_fill(rows, filled, name_field=NAME_FIELD, code_field=CODE_FIELD)
        rows.unlink()
    _package(work, filled)
    for path in (parent, filled, *staged):
        path.unlink()
    return time.perf_counter() - t0


def _mosaic(
    code: str, work: Path, staged: list[Path], parent: Path, filled: Path
) -> None:
    """Edge-mosaic the staged inputs to their parent rows, filling uncovered parts."""
    keys = [p.name.removesuffix("_staged.parquet") for p in staged]
    bases = {catalog_path("original", k).parent for k in keys}
    originals = sorted(f for b in bases for f in b.glob("*_original.parquet"))
    unpaired = _Unpaired()
    mosaic_log = getLogger("topo_tools.api.edge_mosaic")
    mosaic_log.addHandler(unpaired)
    try:
        edge_mosaic(
            input_paths=staged,
            overlay_path=parent,
            output_path=filled,
            issues_path=work / "mosaic_issues.parquet",
            original_paths=originals,
            match_column=MATCH_KEY,
            merge=True,
            overlay_include=[MATCH_KEY, *WLD_COLS],
            input_exclude=[MATCH_KEY],
            fill=ADM0_FILL,
            clean=False,
            fill_schema=True,
            name_field=NAME_FIELD,
            code_field=CODE_FIELD,
            threads=THREADS,
            tmp_dir=work,
        )
    finally:
        mosaic_log.removeHandler(unpaired)
    if originals and unpaired.hit:
        msg = f"{code}: an input pairs with no original by adm{{n}}_pcode"
        raise RuntimeError(msg)


def _fill_rows(conn: object, parent: Path, rows: Path) -> None:
    """Write parent's ADM0 parts as staged rows, for a code with no input."""
    cols = [
        f"{ADM0_FILL[c]}::{t} AS {c}"
        if c in ADM0_FILL
        else f"geom AS {c}"
        if c == "geometry"
        else f"NULL::{t} AS {c}"
        for c, t in staged_columns()
        if c != MATCH_KEY
    ]
    conn.execute(  # type: ignore[attr-defined]
        f"""--sql
        COPY (SELECT {MATCH_KEY}, {", ".join(cols)}, {", ".join(WLD_COLS)}
              FROM '{parent}')
        TO '{rows}' {PARQUET_OPTS}
    """
    )


def _package(work: Path, filled: Path) -> None:
    """Package filled into work/admin{n}, points and lines for levels 1 and up."""
    # Clip seams are accepted; validation errors are reported, not raised.
    package(
        filled,
        work / "{x}.parquet",
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
        min_level=1,
        clean=False,
        block=False,
        threads=THREADS,
        tmp_dir=work,
    )
