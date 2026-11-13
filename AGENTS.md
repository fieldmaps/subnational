# subnational

Pipeline that downloads, processes, and publishes global administrative boundary data.

## Pipeline Stages

```text
app/_01_sources/     → pull catalog/ (PORTOLAN_REMOTE), refresh cod-ab collections in catalog/iso3/, then register changed collections with portolan (--push uploads)
app/_02_build/       → code the published extended layers (topo-tools code-create), edge-mosaic to the world-view ADM0, package and validate into tmp/build.duckdb
app/_03_export/      → write catalog/global/admin{n}/admin{n}{,_points,_lines}.parquet and register them with portolan (--push uploads)
app/publish/         → shared portolan helpers (tiling, metadata, add, readme/check, push) for sources and export
scripts/ingest_erm.py → yearly EuroGeographics ERM release into the catalog/iso3/ collections published from erm (`uv run python -m scripts.ingest_erm <FullEurope dir>`)
```

Entry point: `uv run -m app` (all stages). Single stage: `uv run -m app --step sources` (or `build`, `export`); also honors `STEP` env var.

## Catalog and Sources

`catalog/` is the portolan catalog published to `source.coop/fieldmaps/subnational` and the source of truth. `iso3/{base}/` holds one source's layers per base iso3; `global/admin{n}/` holds the export. Each `iso3/{base}/` collection has:

- `{key}_{tier}.parquet`: one layer per tier, GeoParquet 2.0 (no bbox covering column). An iso3 whose units span several ADM0 clip parts has one extended layer per part (`geo_1_extended`, `geo_2_extended`) beside the single `{base}_original.parquet`; for cod-ab, `PARTS` (`app/config.py`) lists them and step 1 splits the original by part and extends each.
- `{base}_metadata.json`: one source-metadata row per (`key`, `tier`) (`src_*`, `via`, `via_checksum`), the only record of it. `SOURCES_SQL` in `app/_01_sources/schema.py` reads every sidecar as one table.
- Both tiers use the cod-ab extended schema for every source (`adm{n}_name..name3, adm{n}_pcode` for n = lvl..0, then `valid_on, valid_to, version, lang..lang3, iso2, iso3, geometry`), defined in `app/_01_sources/schema.py`.
- `original` tier: the source's own geometry (for `erm`, its units dissolved before extension); `extended` tier: that layer extended past its coastline.

| `src`           | Upstream                                     | Refresh                          |
| --------------- | -------------------------------------------- | -------------------------------- |
| `cod-ab`        | `source.coop/hdx/cod-ab`, latest `cod_ab:admin_level_full` layer; `src_*` from the `cod_ab:*` properties of `original/{iso3}/latest/catalog.json` | every step 1 run when those properties or the upstream `file:checksum` change; replaces any other src except the iso3s in `KEEP` (`app/config.py`); kept if removed upstream |
| `erm`           | EuroGeographics EuroRegionalMap (manual download) | `scripts/ingest_erm.py` per yearly release |
| `cod-ab-legacy` | `data.fieldmaps.io/cod.json`                 | frozen                           |
| `geoboundaries` | `data.fieldmaps.io/geoboundaries.json`       | frozen                           |

`archive/` (gitignored, never read) holds every source's layers per iso3 as `archive/{src}/{base}/`, for switching an iso3 to another source by hand. The build reads every published extended layer and generates `adm{n}_id` (`{ISO3}-{YYYYMMDD}-{seq}...`, numbered within each parent by `adm{n}_pcode`) with topo-tools `code_create`.

ADM0 clip layers: `https://data.source.coop/fieldmaps/international` (or the local `../international/catalog`). The clip is the humanitarian ADM0 with each `CLIP_PARTS` parent (`app/_02_build/config.py`) replaced by its disaggregated parts, renamed `{ISO3}_{n}`. An input key matching a part covers that part; otherwise every part of its iso3 merges under the key.

## Key Constraints

- No PostgreSQL, no PostGIS, no Docker database service.
- Use DuckDB (`ST_Read`, `COPY ... PARQUET_OPTS`) for reading and writing geodata; `gdal vector` only where DuckDB can't.
- `catalog/.portolan/config.yaml` sets `add_bbox: false` and `sort: none` so `portolan add` keeps files as written, and `pmtiles.max_zoom: 12`.
- portolan-cli and tylertoo are project dependencies (`uv sync`). `tile_collection` in `app/publish/utils.py` tiles each `<stem>.parquet` as `<stem>.pmtiles` with tylertoo (max zoom 12), and `portolan add` (no `--pmtiles`) registers the existing tiles.
- `app/publish/fieldmaps_publish.py` runs portolan with the repo-root `.env` loaded, and `--push` goes through its `push()`, which runs `aws s3 sync` with the repo-root `aws.config` (AWS CLI on PATH), `versions.json` last, and raises if any upload fails. Keep it identical to the copies in fieldmaps/international and OCHA-DAP/cod-site.
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
PARQUET_OPTS = "(COMPRESSION ZSTD, COMPRESSION_LEVEL 15, GEOPARQUET_VERSION V2)"
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
