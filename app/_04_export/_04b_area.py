"""Calculate area statistics from the finest global polygons and write Excel."""

from app.config import BUILD_DB, OUTPUTS_DIR
from app.utils import get_conn

from .config import AREA_CRS
from .utils import build_levels, global_path


def main() -> None:
    """Write area stats to outputs/area/."""
    conn = get_conn(BUILD_DB, read_only=True)
    levels = build_levels(conn)
    conn.close()
    if not levels:
        return
    top = max(levels)
    parquet = global_path(top, "polygons")

    out_dir = OUTPUTS_DIR / "area"
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = ", ".join(f"adm{lvl}_id" for lvl in range(top, -1, -1))
    conn = get_conn()
    df = conn.execute(f"""--sql
        SELECT
            {ids}, iso_3,
            ST_Area(
                ST_Transform(geometry, 'EPSG:4326', '{AREA_CRS}', true)
            ) / 1000000 AS area_km
        FROM read_parquet('{parquet}')
    """).df()
    conn.close()

    if df.empty:
        return

    df1 = (
        df.groupby("adm0_id", dropna=False)
        .sum(numeric_only=True, min_count=1)
        .reset_index()
    )
    df1 = df1.rename(columns={"area_km": "area_0_km"})
    df1["area_0_km"] = df1["area_0_km"].astype(int)
    for lvl in levels:
        df2 = df[["adm0_id", f"adm{lvl}_id"]].drop_duplicates(subset=[f"adm{lvl}_id"])
        df2 = df2.groupby("adm0_id", dropna=False).count().reset_index()
        df1 = df1.merge(df2, on="adm0_id")
        df1[f"area_{lvl}_km"] = df1["area_0_km"] / df1[f"adm{lvl}_id"]
        df1[f"area_{lvl}_km"] = df1[f"area_{lvl}_km"].astype(int)
        df1 = df1.drop(columns=[f"adm{lvl}_id"])
    df1.to_excel(out_dir / "area.xlsx", sheet_name="area", index=False)

    for lvl in range(top, -1, -1):
        dfx = (
            df.groupby(f"adm{lvl}_id", dropna=False)
            .sum(numeric_only=True, min_count=1)
            .reset_index()
        )
        dfx["area_km"] = dfx["area_km"].astype(int)
        dfx.to_excel(
            out_dir / f"area_{lvl}.xlsx",
            sheet_name=f"area_{lvl}",
            index=False,
        )
