"""Build catalog/global/adm{n}-{geom}/ from the published extended layers."""

from . import _02a_inputs, _02b_keys, _02c_merge


def main() -> None:
    """Write the ADM0 parent, package every key in parallel, then merge."""
    sources = _02a_inputs.sources()
    _02a_inputs.write_parent(list(sources))
    _02b_keys.build_keys(sources)
    _02c_merge.merge()


if __name__ == "__main__":
    main()
