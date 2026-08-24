# Weight Sensitivity

Why 0.30 for `sector_fit` and not 0.35? Each weight in `app.features.WEIGHTS` is perturbed independently, each
delta renormalized so all six weights still sum to 1.0, and re-run against the default target profile
(`Healthcare Services`, ~$200M). Two separate sweeps, at different granularities, both measuring drift from
the unperturbed top-10 ranking:

- **Chart below** (`scripts/plot_weight_sensitivity.py`): a fine 0.01-step sweep from -0.30 to +0.40 per
  weight, visualization only, nothing persisted but the PNG.
- **Table further down** (`scripts/weight_sensitivity.py`): a coarser ±0.05/±0.10 sweep, persisted to
  `docs/weight_sensitivity_results.json`, also recording Spearman rank correlation, not just overlap count.

![Weight sensitivity: top-10 overlap vs. perturbation, per weight](weight_sensitivity_overlap.png)

Reading the chart: `sector_fit` degrades fastest and furthest of the six (overlap falls to 6/10 at delta
-0.30, the sweep's worst case), consistent with it being the primary driver of which sector a deal even counts
as relevant. `size_fit`, `recency`, and `outcome_quality` bottom out around 8/10 at their respective extremes;
`profile_fit` and `tag_alignment` stay at 9/10 or better across the full -0.30 to +0.40 range, the two most
robust weights. Reproduce with `python scripts/plot_weight_sensitivity.py`.

## Results

| Weight | Delta | New Value | Top-10 Overlap | Spearman rho |
|---|--:|---:|---:|---:|
| outcome_quality | -0.10 | 0.0000 | 9/10 | 0.927 |
| outcome_quality | -0.05 | 0.0526 | 10/10 | 0.927 |
| outcome_quality | +0.05 | 0.1429 | 9/10 | 0.927 |
| outcome_quality | +0.10 | 0.1818 | 9/10 | 0.900 |
| profile_fit | -0.10 | 0.1111 | 10/10 | 0.867 |
| profile_fit | -0.05 | 0.1579 | 10/10 | 0.939 |
| profile_fit | +0.05 | 0.2381 | 9/10 | 0.945 |
| profile_fit | +0.10 | 0.2727 | 9/10 | 0.945 |
| recency | -0.10 | 0.0000 | 9/10 | 0.936 |
| recency | -0.05 | 0.0526 | 9/10 | 0.973 |
| recency | +0.05 | 0.1429 | 10/10 | 0.927 |
| recency | +0.10 | 0.1818 | 10/10 | 0.855 |
| sector_fit | -0.10 | 0.2222 | 9/10 | 0.936 |
| sector_fit | -0.05 | 0.2632 | 9/10 | 0.936 |
| sector_fit | +0.05 | 0.3333 | 10/10 | 0.903 |
| sector_fit | +0.10 | 0.3636 | 9/10 | 0.791 |
| size_fit | -0.10 | 0.1667 | 8/10 | 0.853 |
| size_fit | -0.05 | 0.2105 | 9/10 | 0.918 |
| size_fit | +0.05 | 0.2857 | 10/10 | 0.952 |
| size_fit | +0.10 | 0.3182 | 10/10 | 0.939 |
| tag_alignment | -0.10 | 0.0000 | 10/10 | 0.915 |
| tag_alignment | -0.05 | 0.0000 | 10/10 | 0.915 |
| tag_alignment | +0.05 | 0.0952 | 10/10 | 0.964 |
| tag_alignment | +0.10 | 0.1364 | 10/10 | 0.939 |

## Reading the table

Across all 24 perturbations (±0.05/±0.10 only — a narrower range than the chart above), top-10 overlap ranged
8/10 to 10/10 and Spearman rho ranged 0.791 to 0.973. `sector_fit` is again the most sensitive of the six at
this granularity (mean overlap 9.2/10, mean rho 0.892; rho drops to its table-wide low of 0.791 at +0.10, its
biggest single-weight rank shuffle even before overlap itself drops much). `tag_alignment` is the most robust
(mean overlap 10.0/10, mean rho 0.933) since it's the smallest weight to begin with — consistent with the
chart, where it's also one of the two flattest curves.

Reproduce with `python scripts/weight_sensitivity.py`.
