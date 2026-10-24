"""Register catalog/{extended,original}/ per-iso3 collections with portolan."""

import app.config
from app.config import CATALOG_DIR, SOURCES_TABLE
from app.utils import get_conn

from .config import HOST, SRC_NAMES, TIERS
from .utils import ensure_catalog, license_fields, portolan, write_metadata


def main() -> None:
    """Write metadata.yaml per collection, add, validate, and push with --push."""
    ensure_catalog()
    conn = get_conn()
    df = conn.execute(f"SELECT * FROM read_parquet('{SOURCES_TABLE}')").df()
    rows = df.astype(object).where(df.notna(), None).to_dict("records")
    for tier, (title, description) in TIERS.items():
        write_metadata(
            CATALOG_DIR / tier,
            title=title,
            description=description,
            **license_fields(None, None),
        )
    originals_done = set()
    for row in rows:
        key, base = row["key"], row["key"].split("_")[0]
        name = conn.execute(
            "SELECT any_value(adm0_name) FROM read_parquet(?)",
            [str(CATALOG_DIR / "extended" / key / f"{key}_extended.parquet")],
        ).fetchall()[0][0]
        _add(row, "extended", key, f"{name} ({key.upper()})" if "_" in key else name)
        if base not in originals_done and row["via_original"]:
            originals_done.add(base)
            _add(row, "original", base, name)
    conn.close()
    portolan("metadata", "validate")
    portolan("readme")
    # --fix reports failure while any unfixable warning remains; the next check decides.
    portolan("check", "--fix", "--metadata", strict=False)
    portolan("check", "--data-scope", "local")
    if app.config.PUSH:
        portolan("push", "--dry-run")
        portolan("push")


def _add(row: dict, tier: str, key: str, title: str) -> None:
    """Write one collection's metadata.yaml, then `portolan add` it."""
    producer = (
        [{"name": row["src_name"], "roles": ["producer"]}] if row["src_name"] else []
    )
    write_metadata(
        CATALOG_DIR / tier / key,
        title=title,
        description=f"{SRC_NAMES[row['src']]}, admin level {row['src_lvl']}.",
        **license_fields(row["src_lic"], row["src_url"]),
        providers=[*producer, HOST],
        source_url=row[f"via_{tier}"],
        keywords=[row["iso3"], row["src"]],
    )
    stamp = row["src_update"] or row["src_date"]
    when = ["--datetime", str(stamp)[:10]] if stamp else []
    portolan("add", f"{tier}/{key}", "--pmtiles", *when)


if __name__ == "__main__":
    main()
