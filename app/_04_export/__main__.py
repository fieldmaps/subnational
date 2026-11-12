"""Export stage: write catalog/global/ GeoParquets and register them with portolan."""

from . import _04a_outputs, _04d_publish


def main() -> None:
    """Write the global GeoParquets, then publish them."""
    _04a_outputs.main()
    _04d_publish.main()


if __name__ == "__main__":
    main()
