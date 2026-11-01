"""Run the portolan CLI with tylertoo in place of tippecanoe for `--pmtiles`.

Runs in portolan's uv tool env: `uv tool install portolan-cli --with tylertoo`.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import tylertoo
from portolan_cli.cli import cli
from portolan_cli.viz import pmtiles


def _generate(
    parquet_path: Path,
    pmtiles_path: Path,
    *,
    max_zoom: int | None = None,
    layer: str | None = None,
    **_: object,
) -> None:
    """Tile one GeoParquet with tylertoo, matching portolan's generate_pmtiles."""
    with TemporaryDirectory() as tmp:
        overview = Path(tmp) / "overview.parquet"
        # Every boundary at every zoom: only sub-pixel simplification drops detail.
        tylertoo.overview(
            str(parquet_path),
            str(overview),
            max_zoom=max_zoom or "auto",
            density_drop=False,
            line_thinning=0,
            line_visibility=0,
            polygon_thinning=0,
            polygon_visibility=0,
        )
        tylertoo.export_pmtiles(
            str(overview),
            str(pmtiles_path),
            layer_name=layer or parquet_path.stem,
            tile_size_limit=None,
        )


pmtiles.generate_pmtiles = _generate

if __name__ == "__main__":
    cli()
