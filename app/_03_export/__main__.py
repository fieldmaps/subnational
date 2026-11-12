"""Export stage: write catalog/global/ GeoParquets and register them with portolan."""

from . import _03a_outputs, _03b_publish


def main() -> None:
    """Write the global GeoParquets, then publish them."""
    _03a_outputs.main()
    _03b_publish.main()


if __name__ == "__main__":
    main()
