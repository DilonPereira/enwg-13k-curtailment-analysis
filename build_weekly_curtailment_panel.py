"""
build_weekly_curtailment_panel.py

Aggregates event-level redispatch data into a weekly national renewable
curtailment panel matching SMARD's weekly generation resolution.
"""

import glob
import pandas as pd

RENEWABLE_LABEL = "Erneuerbar"
REDUCE_KEYWORD = "reduzieren"


def load_all_files(pattern: str = "redispatch_*.csv") -> pd.DataFrame:
    """Load and combine redispatch CSV files, dropping exact duplicates."""
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No files matching '{pattern}' found in directory.")

    frames = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8")
        frames.append(df)
        print(f"Loaded {f}: {len(df)} rows")

    combined = pd.concat(frames, ignore_index=True)
    print(f"\nTotal rows before deduplication: {len(combined)}")

    combined = combined.drop_duplicates()
    print(f"Total rows after deduplication:  {len(combined)}")

    return combined


def main():
    df = load_all_files()

    df["begin_dt"] = pd.to_datetime(df["BEGINN_DATUM"], format="%d.%m.%Y", errors="coerce")
    df["week_start"] = df["begin_dt"] - pd.to_timedelta(df["begin_dt"].dt.weekday, unit="D")

    curtailment = df[
        (df["PRIMAERENERGIEART"] == RENEWABLE_LABEL)
        & (df["RICHTUNG"].str.contains(REDUCE_KEYWORD, na=False))
    ].copy()

    print(
        f"\nRows classified as renewable curtailment: {len(curtailment)} "
        f"out of {len(df)} total ({len(curtailment) / len(df):.1%})"
    )

    weekly = (
        curtailment.groupby("week_start")["GESAMTE_ARBEIT_MWH"]
        .sum()
        .reset_index()
        .rename(columns={"GESAMTE_ARBEIT_MWH": "curtailed_mwh_national"})
        .sort_values("week_start")
    )
    weekly["week_start"] = weekly["week_start"].dt.strftime("%Y-%m-%d")

    weekly.to_csv("weekly_curtailment_national.csv", index=False)
    print(f"\nSaved weekly_curtailment_national.csv with {len(weekly)} weeks.")
    print(weekly.tail(10).to_string(index=False))


if __name__ == "__main__":
    main()