"""Export stage: turn tmp/build.duckdb's tables into all on-disk file formats."""

from . import _04a_outputs, _04b_area, _04c_formats, _04d_publish


def main() -> None:
    """Write GeoParquets, area stats, and format conversions, then publish them."""
    _04a_outputs.main()
    _04b_area.main()
    _04c_formats.main()
    _04d_publish.main()


if __name__ == "__main__":
    main()
