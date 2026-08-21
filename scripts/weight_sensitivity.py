"""Weight-sensitivity analysis for the acquirer ranking (offline, one-off)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.features as features
from app.data import load_transactions
from app.ranking import rank_acquirers

TARGET_PROFILE = {
    "sector": "Healthcare Services",
    "deal_size_mm": 200,
    "geography": None,
}
DELTAS = [-0.10, -0.05, 0.05, 0.10]
OUT_JSON = Path("docs/weight_sensitivity_results.json")
OUT_MD = Path("docs/weight_sensitivity.md")


def run_ranking(df, target_profile, weights, top_n):
    original = features.WEIGHTS
    features.WEIGHTS = weights
    try:
        ranked, _ = rank_acquirers(df, target_profile, top_n=top_n)
    finally:
        features.WEIGHTS = original
    return ranked


def _rank_avg(values):
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rho(xs, ys):
    if len(xs) < 2:
        return float("nan")
    rx = _rank_avg(xs)
    ry = _rank_avg(ys)
    n = len(xs)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0.0 or dy == 0.0:
        return float("nan")
    return num / (dx * dy)


def build_summary(rows):
    by_weight = {}
    for r in rows:
        by_weight.setdefault(r["weight"], []).append(r)
    stats = {
        w: (
            sum(x["top10_overlap"] for x in xs) / len(xs),
            sum(x["spearman_rho"] for x in xs) / len(xs),
        )
        for w, xs in by_weight.items()
    }
    most = min(stats, key=lambda w: (stats[w][0], stats[w][1]))
    robust = max(stats, key=lambda w: (stats[w][0], stats[w][1]))
    min_ov = min(r["top10_overlap"] for r in rows)
    max_ov = max(r["top10_overlap"] for r in rows)
    min_rho = min(r["spearman_rho"] for r in rows)
    max_rho = max(r["spearman_rho"] for r in rows)
    return (
        f"Across all 24 perturbations, top-10 overlap ranged {min_ov}/10 to {max_ov}/10 "
        f"and Spearman rho ranged {min_rho:.3f} to {max_rho:.3f}. The ranking is most "
        f"sensitive to `{most}` (mean overlap {stats[most][0]:.1f}/10, mean rho "
        f"{stats[most][1]:.3f}) -- moving it reorders the top 10 the most -- and most "
        f"robust to `{robust}` (mean overlap {stats[robust][0]:.1f}/10, mean rho "
        f"{stats[robust][1]:.3f})."
    )


def main():
    df = load_transactions()
    n_acquirers = int(df["acquirer"].nunique())

    baseline = run_ranking(
        df, TARGET_PROFILE, dict(features.WEIGHTS), top_n=n_acquirers
    )
    baseline_top10 = list(baseline["acquirer"].head(10))
    baseline_full = dict(zip(baseline["acquirer"], baseline["score"]))

    rows = []
    for weight in features.WEIGHTS:
        for delta in DELTAS:
            perturbed = dict(features.WEIGHTS)
            perturbed[weight] = max(0.0, perturbed[weight] + delta)
            total = sum(perturbed.values())
            perturbed = {k: v / total for k, v in perturbed.items()}
            new_value = perturbed[weight]

            ranked = run_ranking(df, TARGET_PROFILE, perturbed, top_n=n_acquirers)
            perturbed_top10 = list(ranked["acquirer"].head(10))
            perturbed_full = dict(zip(ranked["acquirer"], ranked["score"]))

            overlap = len(set(baseline_top10) & set(perturbed_top10))
            union = sorted(set(baseline_top10) | set(perturbed_top10))
            xs = [baseline_full[a] for a in union]
            ys = [perturbed_full[a] for a in union]
            rho = spearman_rho(xs, ys)

            rows.append(
                {
                    "weight": weight,
                    "delta": delta,
                    "new_value": new_value,
                    "top10_overlap": overlap,
                    "spearman_rho": rho,
                    "baseline_top10": baseline_top10,
                    "perturbed_top10": perturbed_top10,
                }
            )

    rows.sort(key=lambda r: (r["weight"], r["delta"]))

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, indent=2))

    header = "| Weight | Delta | New Value | Top-10 Overlap | Spearman rho |\n|---|--:|---:|---:|---:|"
    lines = [header]
    for r in rows:
        lines.append(
            f"| {r['weight']} | {r['delta']:+.2f} | {r['new_value']:.4f} | "
            f"{r['top10_overlap']}/10 | {r['spearman_rho']:.3f} |"
        )
    table = "\n".join(lines)
    print(table)

    md = (
        "# Weight Sensitivity\n\n"
        "How the top-10 acquirer ranking for the default profile "
        "(`Healthcare Services`, ~$200M) moves under per-weight perturbation of "
        "`app.features.WEIGHTS`, each delta renormalized so weights sum to 1.0.\n\n"
        f"{table}\n\n## Reading this\n\n{build_summary(rows)}\n"
    )
    OUT_MD.write_text(md)


if __name__ == "__main__":
    main()
