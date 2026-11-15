"""Build catalog/iso3/ and catalog/global/ from the published extended layers."""

from . import _02a_inputs, _02b_codes, _02c_merge


def main() -> None:
    """Write the ADM0 parent, package every iso3 code in parallel, then merge."""
    sources = _02a_inputs.sources()
    _02a_inputs.write_parent(list(sources))
    _02b_codes.build_codes(sources)
    _02c_merge.merge()


if __name__ == "__main__":
    main()
