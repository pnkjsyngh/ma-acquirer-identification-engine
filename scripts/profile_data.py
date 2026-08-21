import csv
import sys
from collections import Counter
from contextlib import redirect_stdout

DATA_PATH = "data/raw/ma_transactions_500.csv"
REPORT_PATH = "data/profile_report.txt"


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def to_num(value):
    s = value.strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def quantile(values, q):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    pos = q * (len(vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    frac = pos - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def infer_dtype(values):
    nums = [v for v in values if v is not None and not isinstance(v, str)]
    all_int = all(isinstance(v, int) for v in nums)
    if nums and all_int:
        return "int64"
    if nums:
        return "float64"
    return "object"


def print_dist(label, values):
    values = [v for v in values if v is not None]
    if not values:
        print(f"{label}: (no data)")
        return
    parts = [
        ("min", min(values)),
        ("p25", quantile(values, 0.25)),
        ("median", quantile(values, 0.5)),
        ("p75", quantile(values, 0.75)),
        ("max", max(values)),
    ]
    fmt = ", ".join(f"{k}={v:.2f}" for k, v in parts)
    print(f"{label}: {fmt}")


def main():
    with open(DATA_PATH, newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        raw_rows = list(reader)

    rows = [{c: to_num(r.get(c, "")) for c in columns} for r in raw_rows]

    print("=" * 60)
    print("1. ROW COUNT AND COLUMN DTYPES")
    print("=" * 60)
    print(f"rows: {len(rows)}")
    for c in columns:
        print(f"  {c}: {infer_dtype([r[c] for r in rows])}")

    print()
    print("=" * 60)
    print("2. VALUE COUNTS")
    print("=" * 60)
    categoricals = [
        "sector",
        "sub_sector",
        "deal_type",
        "geography",
        "financing_type",
        "outcome",
        "acquirer_type",
        "target_ownership_pre",
    ]
    for c in categoricals:
        print(f"\n-- {c} --")
        counts = Counter(str(r[c]) for r in rows)
        for val, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {val}: {n}")

    print()
    print("=" * 60)
    print("3. HEALTHCARE SERVICES SECTOR")
    print("=" * 60)
    hc = [r for r in rows if r["sector"] == "Healthcare Services"]
    hc_between = [
        r
        for r in hc
        if isinstance(r["deal_size_mm"], (int, float))
        and 100 <= r["deal_size_mm"] <= 400
    ]
    print(f"row count: {len(hc)}")
    print(f"rows with 100 <= deal_size_mm <= 400: {len(hc_between)}")

    print()
    print("=" * 60)
    print("4. NUMERIC DISTRIBUTIONS (overall vs Closed)")
    print("=" * 60)
    metrics = [
        "deal_size_mm",
        "ev_ebitda_multiple",
        "ev_revenue_multiple",
        "ebitda_margin_pct",
        "revenue_growth_pct",
    ]
    closed = [r for r in rows if r["outcome"] == "Closed"]
    for m in metrics:
        print(f"\n-- {m} --")
        print_dist("  overall", [r[m] for r in rows])
        print_dist("  Closed ", [r[m] for r in closed])

    print()
    print("=" * 60)
    print("5. TOP 20 ACQUIRERS BY DEAL COUNT")
    print("=" * 60)
    by_acquirer = {}
    for r in rows:
        by_acquirer.setdefault(r["acquirer"], []).append(r)
    top = sorted(by_acquirer.items(), key=lambda kv: -len(kv[1]))[:20]
    for i, (acq, deals) in enumerate(top, 1):
        types = Counter(d["acquirer_type"] for d in deals)
        sectors = Counter(d["sector"] for d in deals)
        common_type = types.most_common(1)[0][0]
        common_sector = sectors.most_common(1)[0][0]
        print(
            f"  {i:>2}. {acq}: {len(deals)} deals, "
            f"common_type={common_type}, common_sector={common_sector}"
        )

    print()
    print("=" * 60)
    print("6. DATA QUALITY (distinct + missing per column)")
    print("=" * 60)
    for c in columns:
        vals = [r[c] for r in rows]
        distinct = len(set(vals))
        missing = sum(1 for v in vals if v is None or (isinstance(v, str) and v == ""))
        print(f"  {c}: distinct={distinct}, missing={missing}")

    print()
    print("=" * 60)
    print("7. num_bidders and days_to_close (overall vs by outcome)")
    print("=" * 60)
    for m in ["num_bidders", "days_to_close"]:
        print(f"\n-- {m} --")
        print_dist("  overall", [r[m] for r in rows])
        for outcome in ["Closed", "Withdrawn", "Pending", "Terminated", "Rumored"]:
            subset = [r[m] for r in rows if r["outcome"] == outcome]
            print_dist(f"  {outcome:<11}", subset)


if __name__ == "__main__":
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        with redirect_stdout(Tee(sys.stdout, f)):
            main()
