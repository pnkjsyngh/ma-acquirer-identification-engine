"""CSV loading, type coercion, and null handling for the M&A transaction dataset."""

from pathlib import Path

import pandas as pd

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "ma_transactions_500.csv"

NUMERIC_COLUMNS = [
    "deal_year",
    "deal_size_mm",
    "target_revenue_mm",
    "target_ebitda_mm",
    "ebitda_margin_pct",
    "revenue_growth_pct",
    "ev_ebitda_multiple",
    "ev_revenue_multiple",
    "synergy_pct_of_deal",
    "num_bidders",
    "days_to_close",
]

# days_to_close is blank in ~19% of rows; every other numeric column is fully populated.
NULLABLE_COLUMNS = {"days_to_close"}


def load_transactions(csv_path: Path | str = DEFAULT_CSV_PATH) -> pd.DataFrame:
    """Load the M&A transactions CSV with coerced dtypes and parsed tag lists."""
    df = pd.read_csv(csv_path)

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    missing_required = [c for c in NUMERIC_COLUMNS if c not in NULLABLE_COLUMNS and df[c].isna().any()]
    if missing_required:
        raise ValueError(f"Unexpected nulls in required numeric columns: {missing_required}")

    df["strategic_rationale_tags"] = df["strategic_rationale_tags"].fillna("").apply(
        lambda s: [t for t in s.split("|") if t]
    )

    return df
