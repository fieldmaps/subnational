# subnational

Pipeline that downloads, processes, and publishes global administrative boundary data.

## Pipeline Stages

```text
app/_01_sources/     → pull catalog/ (PORTOLAN_REMOTE), refresh cod-ab collections in catalog/source/, then register changed collections with portolan (--push uploads)
app/_02_build/       → per key in parallel: code the published extended layer (topo-tools code-create), edge-mosaic it to its world-view ADM0 parent with its own originals, package it; then merge into catalog/global/adm{n}-{geom}/adm{n}_{geom}.parquet (geom = polygons, points, lines; mirrors the international catalog's adm0-{geom} collections)
app/_03_export/      → tile and register the catalog/global/ collections with portolan (--push uploads)
app/publish/         → shared portolan helpers (tiling, metadata, add, readme/check, push) for sources and export
scripts/ingest_erm.py → yearly EuroGeographics ERM release into the catalog/source/ collections published from erm (`uv run python -m scripts.ingest_erm <FullEurope dir>`)
```

Entry point: `uv run -m app` (all stages). Single stage: `uv run -m app --step sources` (or `build`, `export`); also honors `STEP` env var.

## Catalog and Sources

`catalog/` is the portolan catalog published to `source.coop/fieldmaps/subnational` and the source of truth. `source/{base}/` holds one source's layers per base iso3; `global/adm{n}-{geom}/` holds the export for levels 1 to 4. `adm{n}_polygons` carry every admin and metadata column for levels 0..n; `adm{n}_points` (`id, name..name3, pcode, adm_lvl`) and `adm{n}_lines` (`adm_lvl` 1..n, `a_`/`b_` id, names and pcode labelled at the line's own level) are lean and pair with the international ADM0 layers for country columns, coastlines and borders. Each `source/{base}/` collection has:

- `{key}_{tier}.parquet`: one layer per tier, GeoParquet 2.0 (no bbox covering column). An iso3 whose units span several ADM0 clip parts has one extended layer per part (`geo_1_extended`, `geo_2_extended`) beside the single `{base}_original.parquet`; for cod-ab, `PARTS` (`app/config.py`) lists them and step 1 splits the original by part and extends each.
- `{base}_metadata.json`: one source-metadata row per (`key`, `tier`) (`src_*`, `via`, `via_checksum`), the only record of it. `SOURCES_SQL` in `app/_01_sources/schema.py` reads every sidecar as one table.
- Both tiers use the cod-ab extended schema for every source (`adm{n}_name..name3, adm{n}_pcode` for n = lvl..0, then `valid_on, valid_to, version, lang..lang3, iso2, iso3, geometry`), defined in `app/_01_sources/schema.py`.
- `original` tier: the source's own geometry (for `erm`, its units dissolved before extension); `extended` tier: that layer extended past its coastline, written as a clean coverage by `conform_extended` (`app/_01_sources/schema.py`: topo-tools `topo_detect`, then `topo_clean` on any defect).

| `src`           | Upstream                                     | Refresh                          |
| --------------- | -------------------------------------------- | -------------------------------- |
| `cod-ab`        | `source.coop/hdx/cod-ab`, latest `cod_ab:admin_level_full` layer; `src_*` from the `cod_ab:*` properties of `original/{iso3}/latest/catalog.json` | every step 1 run when those properties or the upstream `file:checksum` change; replaces any other src except the iso3s in `KEEP` (`app/config.py`); kept if removed upstream |
| `erm`           | EuroGeographics EuroRegionalMap (manual download) | `scripts/ingest_erm.py` per yearly release |
| `cod-ab-legacy` | `data.fieldmaps.io/cod.json`                 | frozen                           |
| `geoboundaries` | `data.fieldmaps.io/geoboundaries.json`       | frozen                           |

`archive/` (gitignored, never read) holds every source's layers per iso3 as `archive/{src}/{base}/`, for switching an iso3 to another source by hand.

## Build

Every build is full: `app/_02_build/` runs one job per published extended key (`WORKERS` x `THREADS` in `app/_02_build/config.py`, largest input first), plus one `_fill` job for the ADM0 parts no input covers. Each job works in `tmp/build/keys/{key}/`:

- `code_create` generates `adm{n}_id` (`{KEY}-{YYYYMMDD}-{seq}...`, numbered within each parent by `adm{n}_pcode`), and the layer is padded to every level up to `MAX_LVL` so `fill_schema` copies its deepest level down.
- `edge_mosaic` clips it to its own parent row of `tmp/build/parent.parquet` with only its own iso3's originals, then `package(min_level=1)` writes `admin{n}`, `points` and `lines`.

`_02c_merge.py` writes the merged layers to `tmp/build/global/` and raises unless every level has distinct non-null ids, one point per polygon with a matching id, every expected column, and per-key lines with `adm_lvl` 1..`MAX_LVL`. It then merges the issues and validation summaries into `tmp/build/issues/`, moves the layers into `catalog/global/`, and deletes `tmp/build/keys/`.

ADM0 clip layers: `https://data.source.coop/fieldmaps/international` (or the local `../international/catalog`). The clip is the humanitarian ADM0 with each `CLIP_PARTS` parent (`app/adm0.py`) replaced by its disaggregated parts, renamed `{ISO3}_{n}`. An input key matching a part covers that part; otherwise every part of its iso3 merges under the key.

## Key Constraints

- No PostgreSQL, no PostGIS, no Docker database service.
- Use DuckDB (`ST_Read`, `COPY ... PARQUET_OPTS`) for reading and writing geodata; `gdal vector` only where DuckDB can't.
- `catalog/.portolan/config.yaml` sets `add_bbox: false` and `sort: none` so `portolan add` keeps files as written, and `pmtiles.max_zoom: 12`.
- portolan-cli and tylertoo are project dependencies (`uv sync`). `tile_collection` in `app/publish/utils.py` tiles each `<stem>.parquet` as `<stem>.pmtiles` with tylertoo (max zoom 12), and `portolan add` (no `--pmtiles`) registers the existing tiles.
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
