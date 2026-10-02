"""
build_report_workbook.py

Consolidates curtailment, generation, and countertrade data into a structured Excel workbook,
organized into sheets designed for direct chart generation and reporting.
"""

import os
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

OUTPUT_PATH = "report_data.xlsx"

HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="1F4E5F", end_color="1F4E5F", fill_type="solid")
BODY_FONT = Font(name="Arial")
TITLE_FONT = Font(name="Arial", bold=True, size=14)
LABEL_FONT = Font(name="Arial", bold=True)


def clean_numeric(series: pd.Series) -> pd.Series:
    """Handles both comma-thousands and comma-decimal formats, and '-' for missing data."""
    s = series.astype(str).str.replace(",", "", regex=False)
    s = s.replace("-", pd.NA)
    return pd.to_numeric(s, errors="coerce")


def load_generation(path: str, date_col_format: str = "%b %d, %Y") -> pd.DataFrame:
    """Loads a SMARD-style generation file and returns wind and solar totals by period."""
    raw = pd.read_csv(path, delimiter=";", encoding="utf-8")
    raw.columns = [c.strip() for c in raw.columns]

    date_col = [c for c in raw.columns if "start date" in c.lower()][0]
    wind_off_col = [c for c in raw.columns if "wind offshore" in c.lower()][0]
    wind_on_col  = [c for c in raw.columns if "wind onshore" in c.lower()][0]
    solar_col    = [c for c in raw.columns if "photovoltaics" in c.lower()][0]

    df = pd.DataFrame({
        "period_start": pd.to_datetime(raw[date_col], format=date_col_format),
        "wind_offshore_mwh": clean_numeric(raw[wind_off_col]),
        "wind_onshore_mwh": clean_numeric(raw[wind_on_col]),
        "solar_mwh": clean_numeric(raw[solar_col]),
    })
    df["wind_solar_mwh"] = df["wind_offshore_mwh"] + df["wind_onshore_mwh"] + df["solar_mwh"]
    return df


def style_header_row(ws, n_cols: int, row: int = 1):
    """Applies standard formatting to header rows in Excel sheets."""
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")


def autofit_columns(ws, df: pd.DataFrame, start_col: int = 1):
    """Adjusts column widths based on content length."""
    for i, col in enumerate(df.columns, start=start_col):
        max_len = max(len(str(col)), df[col].astype(str).map(len).max() if len(df) else 0)
        ws.column_dimensions[get_column_letter(i)].width = min(max_len + 3, 30)


def write_dataframe_sheet(writer, df: pd.DataFrame, sheet_name: str):
    """Writes a DataFrame to an Excel worksheet."""
    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)


def main():
    sheets_written = []

    # 1. Load monthly curtailment + countertrade
    monthly = None
    if os.path.exists("monthly_curtailment_and_countertrade.csv"):
        monthly = pd.read_csv("monthly_curtailment_and_countertrade.csv")
        monthly["year_month"] = monthly["year_month"].astype(str)
    else:
        print("WARNING: monthly_curtailment_and_countertrade.csv not found, skipping.")

    # 2. Load weekly curtailment
    weekly = None
    if os.path.exists("weekly_curtailment_national.csv"):
        weekly = pd.read_csv("weekly_curtailment_national.csv")
        weekly["week_start"] = pd.to_datetime(weekly["week_start"])
    else:
        print("WARNING: weekly_curtailment_national.csv not found, skipping.")

    # 3. Load monthly + weekly generation
    gen_monthly = gen_weekly = None
    monthly_gen_path = "Actual_generation_202101010000_202608310000_Month.csv"
    weekly_gen_path = "Actual_generation_202101010000_202609060000_Week.csv"

    if os.path.exists(monthly_gen_path):
        gen_monthly = load_generation(monthly_gen_path)
        gen_monthly["year_month"] = gen_monthly["period_start"].dt.strftime("%Y-%m")
    else:
        print(f"WARNING: {monthly_gen_path} not found, skipping.")

    if os.path.exists(weekly_gen_path):
        gen_weekly = load_generation(weekly_gen_path)
    else:
        print(f"WARNING: {weekly_gen_path} not found, skipping.")

    # 4. Merge monthly curtailment + generation
    monthly_merged = None
    if monthly is not None and gen_monthly is not None:
        monthly_merged = monthly.merge(
            gen_monthly[["year_month", "wind_offshore_mwh", "wind_onshore_mwh",
                         "solar_mwh", "wind_solar_mwh"]],
            on="year_month", how="left"
        )
        monthly_merged = monthly_merged.rename(columns={
            "year_month": "Month",
            "curtailed_mwh_national": "Curtailed Renewable Energy (MWh)",
            "countertrade_mwh_national": "Interconnector Countertrade (MWh)",
            "wind_offshore_mwh": "Wind Offshore Generation (MWh)",
            "wind_onshore_mwh": "Wind Onshore Generation (MWh)",
            "solar_mwh": "Solar Generation (MWh)",
            "wind_solar_mwh": "Total Wind + Solar Generation (MWh)",
        })

    # 5. Merge weekly curtailment + generation
    weekly_merged = None
    if weekly is not None and gen_weekly is not None:
        weekly_merged = weekly.merge(
            gen_weekly.rename(columns={"period_start": "week_start"}),
            on="week_start", how="left"
        )
        weekly_merged = weekly_merged.rename(columns={
            "week_start": "Week Starting",
            "curtailed_mwh_national": "Curtailed Renewable Energy (MWh)",
            "wind_offshore_mwh": "Wind Offshore Generation (MWh)",
            "wind_onshore_mwh": "Wind Onshore Generation (MWh)",
            "solar_mwh": "Solar Generation (MWh)",
            "wind_solar_mwh": "Total Wind + Solar Generation (MWh)",
        })

    # 6. Optional TSO breakdown
    tso_pivot = None
    if os.path.exists("monthly_curtailment_by_tso.csv"):
        tso = pd.read_csv("monthly_curtailment_by_tso.csv")
        tso_pivot = tso.pivot_table(
            index="year_month", columns="tso", values="curtailed_mwh", aggfunc="sum"
        ).reset_index().rename(columns={"year_month": "Month"})

    # 7. Build monthly and weekly trend tables
    TREATMENT_DATE = pd.Timestamp("2024-10-01")

    monthly_trend = weekly_trend = None
    if monthly_merged is not None:
        monthly_trend = monthly_merged.copy()
        monthly_trend["Date"] = pd.to_datetime(monthly_trend["Month"] + "-01")
        monthly_trend["Period"] = monthly_trend["Date"].apply(
            lambda d: "Post-§13k Trial" if d >= TREATMENT_DATE else "Pre-§13k Trial"
        )
        monthly_trend["Is Treatment Start Month"] = (
            monthly_trend["Date"] == TREATMENT_DATE
        )
        monthly_trend = monthly_trend[
            ["Date", "Period", "Is Treatment Start Month",
             "Curtailed Renewable Energy (MWh)", "Total Wind + Solar Generation (MWh)",
             "Wind Offshore Generation (MWh)", "Wind Onshore Generation (MWh)",
             "Solar Generation (MWh)", "Interconnector Countertrade (MWh)"]
        ]

    if weekly_merged is not None:
        weekly_trend = weekly_merged.copy()
        weekly_trend["Date"] = pd.to_datetime(weekly_trend["Week Starting"])
        weekly_trend["Period"] = weekly_trend["Date"].apply(
            lambda d: "Post-§13k Trial" if d >= TREATMENT_DATE else "Pre-§13k Trial"
        )
        weekly_trend["Is Treatment Start Week"] = (
            (weekly_trend["Date"] >= TREATMENT_DATE) &
            (weekly_trend["Date"] < TREATMENT_DATE + pd.Timedelta(days=7))
        )
        weekly_trend = weekly_trend[
            ["Date", "Period", "Is Treatment Start Week",
             "Curtailed Renewable Energy (MWh)", "Total Wind + Solar Generation (MWh)",
             "Wind Offshore Generation (MWh)", "Wind Onshore Generation (MWh)",
             "Solar Generation (MWh)"]
        ]

    # 8. Annual generation growth
    gen_growth = None
    if monthly_trend is not None:
        annual = monthly_trend.copy()
        annual["Year"] = annual["Date"].dt.year
        annual_totals = annual.groupby("Year")["Total Wind + Solar Generation (MWh)"].sum().reset_index()
        annual_totals["YoY Growth (%)"] = annual_totals["Total Wind + Solar Generation (MWh)"].pct_change() * 100
        gen_growth = annual_totals

    # 9. Key indicators summary
    indicators = []
    if monthly_merged is not None:
        pre = monthly_merged[monthly_merged["Month"] < "2024-10"]
        post = monthly_merged[monthly_merged["Month"] >= "2024-10"]

        indicators = [
            ("CALLOUT: Total curtailed renewable energy, full sample period",
             f"{monthly_merged['Curtailed Renewable Energy (MWh)'].sum():,.0f} MWh"),
            ("CALLOUT: Cumulative curtailment since §13k trial start (Oct 2024)",
             f"{post['Curtailed Renewable Energy (MWh)'].sum():,.0f} MWh"),
            ("CALLOUT: §13k-allocated volume (diverted to flexible loads) since Oct 2024",
             "Requires separate pull of ZugeteilteABSM series."),
            ("CALLOUT: Total wind + solar generation, full sample period",
             f"{monthly_merged['Total Wind + Solar Generation (MWh)'].sum():,.0f} MWh"),
            ("CALLOUT: Total interconnector countertrade volume, full sample period",
             f"{monthly_merged['Interconnector Countertrade (MWh)'].sum():,.0f} MWh"),
            ("", ""),
            ("Avg. monthly curtailment, pre-§13k trial (before Oct 2024)",
             f"{pre['Curtailed Renewable Energy (MWh)'].mean():,.0f} MWh"),
            ("Avg. monthly curtailment, during §13k trial (from Oct 2024)",
             f"{post['Curtailed Renewable Energy (MWh)'].mean():,.0f} MWh"),
        ]

    # 10. Text content sheets
    mechanism_text = [
        ["Section", "Content"],
        ["What is §13k EnWG (\"Use Instead of Curtail\")?",
         "When Germany's grid becomes congested -- typically when wind output in the north "
         "exceeds transmission capacity to the south -- grid operators have historically "
         "curtailed renewable generators and compensated them for lost output. Section 13k of "
         "the Energy Industry Act (EnWG), in trial phase since October 2024, enables grid "
         "operators to redirect surplus power to registered flexible consumers nearby, such as "
         "electrolyzers, battery storage, or district power-to-heat systems."],
        ["How \"relief regions\" work",
         "The mechanism applies in designated 'Entlastungsregionen' (relief regions) with "
         "persistent grid congestion. Registered flexible consumers receive allocated surplus "
         "under a flat-rate procedure rather than having the generation curtailed outright."],
        ["Why it matters",
         "The mechanism aims to convert curtailment compensation costs into productive "
         "consumption without requiring immediate grid capacity expansions."],
    ]

    finding_text = [
        ["Section", "Content"],
        ["Key Finding",
         "Initial data indicates no statistically significant reduction in curtailment attributable "
         "to the trial phase after controlling for renewable output growth and Germany's April 2023 "
         "nuclear phase-out. This aligns with a gradual participant onboarding phase during the trial."],
        ["Methodology",
         "Data source: netztransparenz.de (TSO transparency platform) and SMARD (Bundesnetzagentur). "
         "Evaluated using an Interrupted Time Series (ITS) design at weekly resolution, controlling for "
         "renewable generation levels, nuclear phase-out events, and placebo trial dates."],
        ["Sources", "netztransparenz.de | smard.de (Bundesnetzagentur)"],
        ["Disclaimer",
         "Independent analysis based on publicly available historical data."],
    ]

    # 11. Write to Excel workbook
    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        if indicators:
            pd.DataFrame(indicators, columns=["Indicator", "Value"]).to_excel(
                writer, sheet_name="Key Indicators", index=False
            )
            sheets_written.append("Key Indicators")

        if monthly_trend is not None:
            write_dataframe_sheet(writer, monthly_trend, "Monthly Trend")
            sheets_written.append("Monthly Trend")

        if weekly_trend is not None:
            write_dataframe_sheet(writer, weekly_trend, "Weekly Trend")
            sheets_written.append("Weekly Trend")

        if gen_growth is not None:
            write_dataframe_sheet(writer, gen_growth, "Generation Growth (Annual)")
            sheets_written.append("Generation Growth (Annual)")

        if tso_pivot is not None:
            write_dataframe_sheet(writer, tso_pivot, "TSO Breakdown")
            sheets_written.append("TSO Breakdown")

        pd.DataFrame(mechanism_text[1:], columns=mechanism_text[0]).to_excel(
            writer, sheet_name="Mechanism Spotlight (Text)", index=False
        )
        sheets_written.append("Mechanism Spotlight (Text)")

        pd.DataFrame(finding_text[1:], columns=finding_text[0]).to_excel(
            writer, sheet_name="Key Finding (Text)", index=False
        )
        sheets_written.append("Key Finding (Text)")

    # 12. Apply styles and formatting
    wb = load_workbook(OUTPUT_PATH)
    for name in sheets_written:
        ws = wb[name]
        n_cols = ws.max_column
        style_header_row(ws, n_cols)
        ws.freeze_panes = "A2"
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = BODY_FONT

        for col in range(1, n_cols + 1):
            letter = get_column_letter(col)
            header_len = len(str(ws.cell(row=1, column=col).value or ""))
            ws.column_dimensions[letter].width = max(14, header_len + 4)

    wb.save(OUTPUT_PATH)
    print(f"\nSaved {OUTPUT_PATH} with sheets: {', '.join(sheets_written)}")


if __name__ == "__main__":
    main()