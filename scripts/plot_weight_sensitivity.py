"""Fine-grained sweep of top-10 overlap vs weight perturbation, plotted.

Same perturbation machinery as weight_sensitivity.py but at 0.01 granularity over a
wider range so the overlap fall-off is visible. Purely for visualization -- nothing is
stored here; the persisted 0.05-increment results stay in docs/weight_sensitivity_*.json/md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.features as features
from app.data import load_transactions
from app.ranking import rank_acquirers

TARGET_PROFILE = {
    "sector": "Healthcare Services",
    "deal_size_mm": 200,
    "geography": None,
}
DELTA_MIN = -0.30
DELTA_MAX = 0.40
DELTA_STEP = 0.01
OUT_PNG = Path("docs/weight_sensitivity_overlap.png")


def run_ranking(df, target_profile, weights, top_n):
    original = features.WEIGHTS
    features.WEIGHTS = weights
    try:
        ranked, _ = rank_acquirers(df, target_profile, top_n=top_n)
    finally:
        features.WEIGHTS = original
    return ranked


def overlap_series(df, target_profile, weight, deltas):
    n_acquirers = int(df["acquirer"].nunique())
    baseline = set(
        run_ranking(df, target_profile, dict(features.WEIGHTS), n_acquirers)[
            "acquirer"
        ].head(10)
    )
    overlaps = []
    for delta in deltas:
        perturbed = dict(features.WEIGHTS)
        perturbed[weight] = max(0.0, perturbed[weight] + delta)
        total = sum(perturbed.values())
        perturbed = {k: v / total for k, v in perturbed.items()}
        top10 = set(
            run_ranking(df, target_profile, perturbed, n_acquirers)["acquirer"].head(10)
        )
        overlaps.append(len(baseline & top10))
    return overlaps


def first_departure(deltas, overlaps):
    """Smallest |delta| at which overlap first drops below the baseline 10."""
    for i, delta in enumerate(deltas):
        if overlaps[i] < 10:
            return delta
    return None


def main():
    df = load_transactions()
    n_steps = int((DELTA_MAX - DELTA_MIN) / DELTA_STEP + 0.5) + 1
    deltas = [round(DELTA_MIN + i * DELTA_STEP, 4) for i in range(n_steps)]

    weights = list(features.WEIGHTS)
    fig, axes = plt.subplots(2, 3, figsize=(14, 7), sharex=True, sharey=True)

    for ax, weight in zip(axes.flat, weights):
        overlaps = overlap_series(df, TARGET_PROFILE, weight, deltas)
        min_overlap = min(overlaps)
        min_delta = deltas[overlaps.index(min_overlap)]
        depart = first_departure(deltas, overlaps)

        ax.axhline(10, color="lightgray", linestyle="--", linewidth=1)
        ax.axvline(0.0, color="gray", linestyle="--", linewidth=0.8)
        ax.plot(deltas, overlaps, color="steelblue", linewidth=1.5, zorder=3)
        ax.set_title(f"{weight} (baseline {features.WEIGHTS[weight]:.2f})")
        ax.set_ylim(0, 10.8)
        ax.set_yticks(range(0, 11))
        ax.grid(alpha=0.3)

        note = f"min {min_overlap}/10 @ {min_delta:+.2f}"
        if depart is not None:
            note += f"\nfalls off @ {depart:+.2f}"
        ax.text(
            0.03,
            0.03,
            note,
            transform=ax.transAxes,
            fontsize=8,
            va="bottom",
            bbox=dict(fc="white", ec="none", alpha=0.7),
        )

        print(f"{weight:>16}: min overlap {min_overlap}/10 at delta {min_delta:+.2f}")

    fig.suptitle(
        "Acquirer-ranking sensitivity to WEIGHTS \u2014 top-10 overlap vs baseline "
        "(Healthcare Services ~$200M profile)",
        fontsize=12,
    )
    for ax in axes[-1]:
        ax.set_xlabel("delta added to weight (renormalized to sum 1.0)")
    for ax in axes[:, 0]:
        ax.set_ylabel("top-10 overlap with baseline")

    fig.tight_layout(rect=[0, 0, 1, 0.96])

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    if plt.get_backend().lower() != "agg":
        plt.show()
    print(f"saved plot -> {OUT_PNG}")


if __name__ == "__main__":
    main()
