"""Run topo-tools validate on each packaged admin{n} layer."""

from logging import getLogger

from topo_tools.api import validate as topo_validate

from ._03b_clip import CLIP_DIR
from .config import CODE_FIELD, NAME_FIELD

logger = getLogger(__name__)


def validate(levels: list[int]) -> None:
    """Validate every admin{n}.parquet, non-blocking; reports go to clip/validate/."""
    out_dir = CLIP_DIR / "validate"
    for lvl in levels:
        if not topo_validate(
            CLIP_DIR / f"admin{lvl}.parquet",
            out_dir,
            name_field=NAME_FIELD,
            code_field=CODE_FIELD,
            threads=4,
        ):
            logger.warning("admin%d: validate reported errors, see %s", lvl, out_dir)
