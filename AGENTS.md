# subnational

Pipeline that downloads, processes, and publishes global administrative boundary data.

## Pipeline Stages

```text
app/_01_sources/     → pull catalog/ (PORTOLAN_REMOTE), back up cod-ab into catalog/cod-ab/, write tmp/sources/sources.parquet
app/_02_publish/     → register every catalog/{src}/{base} collection with portolan (--push uploads)
app/_03_build/       → stage the selected extended layers, edge-match with topo-tools into tmp/build.duckdb
app/_04_export/      → write GeoParquets, format conversions, area stats, and catalog/global/ collections
scripts/migrate_fieldmaps.py → one-time copy of data.fieldmaps.io layers into catalog/ (delete after migration)
scripts/ingest_erm.py → yearly EuroGeographics ERM release into catalog/erm/ (`uv run python -m scripts.ingest_erm <FullEurope dir>`)
```

Entry point: `uv run -m app` (all stages). Single stage: `uv run -m app --step sources` (or `publish`, `build`, `export`); also honors `STEP` env var.

## Catalog and Sources

`catalog/` is the portolan catalog published to `source.coop/fieldmaps/subnational`. It backs up every upstream layer as one collection per source and base iso3, `catalog/{src}/{base}/`:

- `{key}_{tier}.parquet`: one layer per tier, GeoParquet 2.0 (no bbox covering column). Multi-extent keys (`pak_1_extended`, `pak_2_extended`) sit beside the single `{base}_original.parquet`.
- `{base}_metadata.json`: one source-metadata row per (`key`, `tier`) (`src_*`, `via`), the only record of it.
- Both tiers use the cod-ab extended schema for every source (`adm{n}_name..name3, adm{n}_pcode` for n = lvl..0, then `valid_on, valid_to, version, lang..lang3, iso2, iso3, geometry`), defined in `app/_01_sources/schema.py`.
- `original` tier: the source's own geometry (for `erm`, its units dissolved before extension); `extended` tier: that layer extended past its coastline.

| Priority    | `src`           | Upstream                                     | Refresh                          |
| ----------- | --------------- | -------------------------------------------- | -------------------------------- |
| 1 (highest) | `cod-ab`        | `source.coop/hdx/cod-ab`, latest finest level | every step 1 run; kept if removed upstream |
| 2           | `erm`           | EuroGeographics EuroRegionalMap (manual download) | `scripts/ingest_erm.py` per yearly release |
| 3           | `cod-ab-legacy` | `data.fieldmaps.io/cod.json`                 | migrated once                    |
| 4           | `geoboundaries` | `data.fieldmaps.io/geoboundaries.json`       | migrated once                    |

`sources.parquet` marks one `selected` src per base iso3 by priority, or by the per-iso3 `PREFER` override in `app/config.py`. The build reads only selected layers and generates `adm{n}_id` from `adm{n}_pcode`.

ADM0 clip layers: `https://data.source.coop/fieldmaps/international` (or the local `../adm0-generator/catalog`).

## Key Constraints

- No PostgreSQL, no PostGIS, no Docker database service.
- Use DuckDB (`ST_Read`, `COPY ... PARQUET_OPTS`) for reading and writing geodata; `gdal vector` only where DuckDB can't.
- `.portolan/config.yaml` sets `add_bbox: false` and `sort: none` so `portolan add` keeps files as written, and `pmtiles.max_zoom: 10`.
- portolan runs through `app/_02_publish/tylertoo_portolan.py`, which tiles `--pmtiles` with tylertoo; install with `uv tool install portolan-cli --with tylertoo`.
- DuckDB built-in GDAL (`FORMAT GDAL`) handles GPKG/GDB/XLSX export.

## DuckDB Patterns

```python
conn = duckdb.connect()
conn.execute("LOAD spatial;")

# Read GeoParquet
conn.execute(f"CREATE TABLE src AS SELECT * FROM read_parquet('{path}')")

# Glob-merge (union_by_name handles column differences)
conn.execute(f"CREATE TABLE merged AS SELECT * FROM read_parquet('{dir}/*.parquet', union_by_name=true)")

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
uv run ruff check && uv run ruff format
```

## Editing Notes

A PostToolUse ruff hook runs automatically after every file write or edit. Because ruff removes unused imports immediately, **always include the usage of a new import in the same Edit/Write call** — never add imports in one edit and their usage in a follow-up edit, or ruff will strip them between the two calls.
