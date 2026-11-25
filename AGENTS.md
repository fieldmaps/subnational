# subnational

Pipeline that downloads, processes, and publishes global administrative boundary data.

## Pipeline Stages

```text
app/_01_sources/     → pull catalog/ (PORTOLAN_REMOTE), refresh cod-ab collections in catalog/source/, then register changed collections with portolan (--push uploads)
app/_02_build/       → per world-view iso3 in parallel: code its published extended layers (topo-tools code-create), edge-mosaic them to its ADM0 parent rows with their originals, package them; then write catalog/iso3/{iso3}/adm{n}_{geom}.parquet and their union catalog/global/adm{n}-{geom}/adm{n}_{geom}.parquet (geom = polygons, points, lines; mirrors the international catalog's adm0-{geom} collections)
app/_03_export/      → tile and register the catalog/iso3/ and catalog/global/ collections with portolan (--push uploads)
app/publish/         → shared portolan helpers (tiling, metadata, add, readme/check, push) for sources and export
scripts/ingest_erm.py, scripts/ingest_egm.py → yearly EuroGeographics ERM or EGM release into the catalog/source/ collections published from erm or egm (`uv run python -m scripts.ingest_erm <dir with data/FullEurope/FullEurope.gpkg>`, `uv run python -m scripts.ingest_egm <dir with DATA/FullEurope/EuroGlobalMap_*.gpkg>`); `--icc` also writes a listed country with no collection or one from a lower src (`adopt`), and a run without it logs those as adoption candidates and each written layer's unit counts beside the published ones, both sharing `scripts/_ebm.py`
```

Entry point: `uv run -m app` (all stages). Single stage: `uv run -m app --step sources` (or `build`, `export`); also honors `STEP` env var.

## Catalog and Sources

`catalog/` is the portolan catalog published to `source.coop/fieldmaps/subnational` and the source of truth. `source/{base}/` holds one source's layers per base iso3; `iso3/{iso3}/` holds the edge-matched layers of one world-view iso3 (`iso3` of `parent.parquet`) for levels 1 to 4, and `global/adm{n}-{geom}/` their union, one collection per layer. `adm{n}_polygons` carry every admin column for levels 0..n and the `src_*` source metadata columns except `src_lang*`, `area_sqkm` (Equal Earth) and `level`, the deepest real level a unit represents (its source depth up to n, 0 for an ADM0 fill); `adm{n}_points` (`id, name..name3, pcode, level`, the polygon's `level`) and `adm{n}_lines` (`level` 1..n, each line once at the coarsest level it bounds, `a_iso3`/`b_iso3` world-view iso3 of each side, `a_`/`b_` id, names and pcode labelled at the line's own level) are lean and pair with the international ADM0 layers for country columns, coastlines and borders. Each `source/{base}/` collection has:

- `{key}_{tier}.parquet`: one layer per tier, GeoParquet 2.0 (no bbox covering column). An iso3 whose units span several ADM0 clip parts has one extended layer per part (`geo_1_extended`, `geo_2_extended`) beside the single `{base}_original.parquet`; `PARTS` (`app/config.py`) lists them, and the cod-ab refresh and `scripts/_ebm.py` split the original by part and extend each (`split_extended`).
- `{base}_metadata.json`: one source-metadata row per (`key`, `tier`) (`src_*`, `via`, `via_checksum`), the only record of it. `SOURCES_SQL` in `app/_01_sources/schema.py` reads every sidecar as one table.
- Both tiers use the cod-ab extended schema for every source (`adm{n}_name..name3, adm{n}_pcode` for n = lvl..0, then `valid_from, valid_to, version, lang..lang3, iso2, iso3, geometry`), defined in `app/_01_sources/schema.py`.
- `original` tier: the source's own geometry (for `erm` and `egm`, its units dissolved before extension; for `egm`, also cleaned by `conform_extended`); `extended` tier: that layer extended past its coastline, written as a clean coverage by `conform_extended` (`app/_01_sources/schema.py`: topo-tools `topo_detect`, then on any defect each unit part lying wholly inside another unit is cut from the enclosing unit and `topo_clean` runs).

| `src`           | Upstream                                     | Refresh                          |
| --------------- | -------------------------------------------- | -------------------------------- |
| `cod-ab`        | `source.coop/hdx/cod-ab`, latest `cod_ab:admin_level_full` layer; `src_*` from the `cod_ab:*` properties of `original/{iso3}/latest/catalog.json` | every step 1 run when those properties or the upstream `file:checksum` change; replaces any other src except the iso3s in `KEEP` (`app/config.py`); kept if removed upstream |
| `erm`           | EuroGeographics EuroRegionalMap (manual download) | `scripts/ingest_erm.py` per yearly release; replaces `egm` and the frozen srcs |
| `egm`           | EuroGeographics EuroGlobalMap (manual download); Serbia from `PolbndA_optionRS` | `scripts/ingest_egm.py` per yearly release; replaces the frozen srcs |
| `cod-ab-legacy` | `data.fieldmaps.io/cod.json`                 | frozen                           |
| `geoboundaries` | `data.fieldmaps.io/geoboundaries.json`       | frozen                           |

`archive/` (gitignored, never read) holds every source's layers per iso3 as `archive/{src}/{base}/`, for switching an iso3 to another source by hand.

## Build

Every build is full: `app/_02_build/` runs one job per world-view iso3 (`WORKERS` x `THREADS` in `app/_02_build/config.py`, largest inputs first), each working in `tmp/build/iso3/{iso3}/`:

- `code_create` generates `adm{n}_id` (`{KEY}-{YYYYMMDD}-{seq}...`, numbered within each parent by `adm{n}_pcode`), and the layer is padded to every level up to `MAX_LVL` so `fill_schema` copies its deepest level down.
- `edge_mosaic` clips the code's keys to its parent rows of `tmp/build/parent.parquet` with only their bases' originals, filling parts no key covers from `ADM0_FILL`, then `package(min_level=1)` writes `admin{n}`, `points` and `lines`. A key whose base original has one unit is not an input, a source key with no parent row raises, and a code with no input key goes through `schema_fill` and `package` alone. A code with several ADM0 parts gets its lines from `package_lines` on a copy with one `adm0_id`, so edges between parts are lines at their adm1..4 level.

`_02c_merge.py` writes each code's 12 layers, then their union to `tmp/build/global/`, all in Hilbert order (the code's layers in 8 MB row groups, `ISO3_PARQUET_OPTS`), and raises unless every global level has distinct non-null ids, one point per polygon with a matching id, every expected column, and per-code lines with `adm_lvl` 1..`MAX_LVL`. It then merges the issues and validation summaries into `tmp/build/issues/`, moves the layers into `catalog/global/` and `catalog/iso3/{iso3}/` (`portolan rm` on codes not built), and deletes `tmp/build/iso3/`.

ADM0 clip layers: `https://data.source.coop/fieldmaps/international` (or the local `../international/catalog`). The clip is the humanitarian ADM0 with each `CLIP_PARTS` parent (`app/adm0.py`) replaced by its disaggregated parts, renamed `{ISO3}_{n}`. An input key matching a part covers that part; otherwise every part of its iso3 merges under the key.

## Key Constraints

- No PostgreSQL, no PostGIS, no Docker database service.
- Use DuckDB (`ST_Read`, `COPY ... PARQUET_OPTS`) for reading and writing geodata; `gdal vector` only where DuckDB can't.
- `catalog/.portolan/config.yaml` sets `add_bbox: false` and `sort: none` so `portolan add` keeps files as written, and `pmtiles.max_zoom: 12`.
- portolan-cli and tylertoo are project dependencies (`uv sync`). `tile_collection` in `app/publish/utils.py` tiles each non-empty `<stem>.parquet` as `<stem>.pmtiles` with tylertoo (max zoom 12), and `portolan add` (no `--pmtiles`) registers the existing tiles.
- `app/publish/fieldmaps_publish.py` runs portolan with the repo-root `.env` loaded, and `--push` goes through its `push()`, which runs `aws s3 sync` with the repo-root `aws.config` (AWS CLI on PATH), `versions.json` last, and raises if any upload fails. Keep it identical to the copies in fieldmaps/international, OCHA-DAP/cod-app and OCHA-DAP/adm0-app.
- DuckDB built-in GDAL (`FORMAT GDAL`) handles GPKG/GDB/XLSX export.

## DuckDB Patterns

```python
conn = duckdb.connect()
conn.execute("LOAD spatial;")

# Read GeoParquet
conn.execute(f"CREATE TABLE src AS SELECT * FROM read_parquet('{path}')")

# Glob-merge (union_by_name handles column differences)
conn.execute(
    f"CREATE TABLE merged AS SELECT * FROM read_parquet('{dir}/*.parquet', union_by_name=true)"
)

# Write GeoParquet (PARQUET_OPTS defined in app/config.py)
PARQUET_OPTS = "(COMPRESSION ZSTD, COMPRESSION_LEVEL 15, GEOPARQUET_VERSION V2, ROW_GROUP_SIZE_BYTES '32MB')"
conn.execute(f"COPY (SELECT * FROM t) TO '{dest}' {PARQUET_OPTS}")

# Export GPKG/GDB/XLSX via DuckDB's built-in GDAL
conn.execute(f"COPY (SELECT * FROM src) TO '{dest}' (FORMAT GDAL, DRIVER 'GPKG')")
```

## Development Commands

```bash
uv sync
uv run -m app
uv run -m app --step sources
uv run -m app --step sources --force-pmtiles   # rebuild every PMTiles after tiling settings change
uv run ruff check && uv run ruff format
```

## Editing Notes

A PostToolUse ruff hook runs automatically after every file write or edit. Because ruff removes unused imports immediately, **always include the usage of a new import in the same Edit/Write call** — never add imports in one edit and their usage in a follow-up edit, or ruff will strip them between the two calls.
