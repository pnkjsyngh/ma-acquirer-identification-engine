# Dataset

`data/raw/ma_transactions_500.csv` -- 500 U.S. healthcare M&A transactions, one row per deal, 24 columns.
This is the full EDA behind the ranking/feature design decisions referenced throughout the README; the raw
profiling output this was built from is `data/profile_report.txt`.

## Shape and data quality

- **500 rows, 24 columns.** `transaction_id` and `target_company` are both 500-distinct (one row per deal, no
  repeat targets). `acquirer` has 107 distinct values -- the full acquirer universe the ranking pipeline scores
  against.
- **Only one column has missing values:** `days_to_close`, missing in 94/500 rows (~19%). This lines up exactly
  with the 94 non-`Closed` deals (500 - 406 `Closed` = 94) -- `days_to_close` is only meaningful once a deal has
  actually closed, so this is a structural property of the data, not a quality bug. No ranking signal uses this
  column, so it doesn't affect scores either way.
- Every other column is fully populated.

| Column | Dtype | Distinct | Missing |
|---|---|---|---|
| `transaction_id` | object | 500 | 0 |
| `target_company` | object | 500 | 0 |
| `acquirer` | object | 107 | 0 |
| `sector` | object | 10 | 0 |
| `sub_sector` | object | 10 | 0 |
| `deal_year` | int64 | 10 | 0 |
| `deal_quarter` | object | 4 | 0 |
| `deal_type` | object | 10 | 0 |
| `geography` | object | 10 | 0 |
| `financing_type` | object | 7 | 0 |
| `deal_size_mm` | float64 | 462 | 0 |
| `target_revenue_mm` | float64 | 429 | 0 |
| `target_ebitda_mm` | float64 | 276 | 0 |
| `ebitda_margin_pct` | float64 | 226 | 0 |
| `revenue_growth_pct` | float64 | 194 | 0 |
| `ev_ebitda_multiple` | float64 | 181 | 0 |
| `ev_revenue_multiple` | float64 | 333 | 0 |
| `synergy_pct_of_deal` | float64 | 150 | 0 |
| `outcome` | object | 5 | 0 |
| `strategic_rationale_tags` | object | 138 | 0 |
| `num_bidders` | int64 | 5 | 0 |
| `days_to_close` | float64 | 254 | 94 |
| `acquirer_type` | object | 2 | 0 |
| `target_ownership_pre` | object | 4 | 0 |

`sector` and `sub_sector` are identical in this dataset (same 10 values, same counts) -- effectively one signal,
not two independent ones.

## Categorical breakdowns

**Sector** (10 values) -- Behavioral Health is the largest at 70 deals, Pharma/Biotech the smallest at 38:

| Sector | Deals |
|---|---|
| Behavioral Health | 70 |
| Home Health/Hospice | 62 |
| Physician Groups | 60 |
| Health IT | 50 |
| Dental | 46 |
| Healthcare Services | 46 |
| Health Insurance | 43 |
| Revenue Cycle | 43 |
| Medical Devices | 42 |
| Pharma/Biotech | 38 |

**Deal type** (10 values): Leveraged Buyout (66), Platform Investment (60), Bolt-on Acquisition (57),
Recapitalization (56), SPAC Merger (50), Strategic Acquisition (48), Management Buyout (47), Minority
Investment (42), Merger of Equals (40), Carve-out (34).

**Geography** (10 values): Midwest (63), Southeast (59), Mountain West (53), Mid-Atlantic (51), National (51),
Northeast (51), Great Plains (46), Multi-Regional (44), West Coast (42), Southwest (40).

**Outcome** (5 values): Closed (406, 81%), Withdrawn (49), Pending (21), Terminated (14), Rumored (10).

**Acquirer type** (2 values): Financial Sponsor (290, 58%), Strategic (210, 42%) -- confirms the dataset isn't
strategics-only, which matters for the "not an all-PE shortlist" check in the README's spot-check notes.

**Target ownership pre-deal** (4 values): Private (208), PE-Backed (141), Public (76), Non-Profit (75).

**Financing type** (7 values): Stock (80), All Cash (79), Seller Financing (74), Mixed (69), Cash + Stock (68),
Leveraged (66), Earnout (64).

## Numeric distributions (overall vs. `Closed`-only)

Closed-only distributions are near-identical to the overall ones across every numeric field -- outcome doesn't
introduce a meaningful selection bias in this dataset:

| Field | Overall (min / p25 / median / p75 / max) | Closed only |
|---|---|---|
| `deal_size_mm` | 6.10 / 41.10 / 153.60 / 458.82 / 14,353.70 | 6.10 / 47.25 / 166.00 / 487.40 / 14,353.70 |
| `ev_ebitda_multiple` | 7.20 / 12.30 / 15.75 / 19.20 / 29.70 | 7.30 / 12.33 / 15.70 / 19.10 / 29.70 |
| `ev_revenue_multiple` | 0.30 / 1.90 / 2.69 / 4.67 / 8.45 | 0.30 / 1.91 / 2.70 / 4.67 / 8.45 |
| `ebitda_margin_pct` | 1.70 / 11.00 / 15.50 / 21.52 / 33.60 | 1.70 / 10.90 / 15.65 / 21.58 / 33.60 |
| `revenue_growth_pct` | 2.70 / 9.07 / 13.20 / 17.20 / 27.70 | 2.70 / 9.20 / 13.40 / 17.20 / 27.70 |

`deal_size_mm` has a long right tail (max $14.4B vs. median $154M) -- a handful of mega-deals sit far above the
assessment's ~$100-400M target band. `size_fit` (`app/features.py`) is a distance-based signal specifically so
these outliers don't dominate scoring for a mid-market target.

**`num_bidders`** (overall min/p25/median/p75/max: 1 / 2 / 2 / 3 / 5) is fairly stable across outcomes, with one
exception: `Terminated` deals skew higher (median 3, p75 4) -- more competitive processes may correlate with
deals that fall apart, consistent with `ranking.py`'s "5+ bidders" risk-flag candidate.

**`days_to_close`** (only populated for `Closed` deals): min 45, p25 140, median 239.5, p75 322.75, max 420 days.

## Healthcare Services sector (the assessment's default target)

46 rows total; 12 fall within the assessment's ~$100-400M target band (`100 <= deal_size_mm <= 400`) -- the
direct comparable-deal pool for the default profile before any sector-adjacency widening.

## Top acquirers by deal count

The 15 most active acquirers are all Financial Sponsors -- expected, since PE firms transact far more
frequently than strategic acquirers in this dataset. The most active Strategic acquirers appear starting at
rank 16, each with meaningfully fewer deals (5-6 vs. 14-25):

| Rank | Acquirer | Deals | Type | Most common sector |
|---|---|---|---|---|
| 1 | Blackstone | 25 | Financial Sponsor | Health Insurance |
| 2 | Nordic Capital | 24 | Financial Sponsor | Physician Groups |
| 3 | Bain Capital | 24 | Financial Sponsor | Physician Groups |
| 4 | Vista Equity | 24 | Financial Sponsor | Behavioral Health |
| 5 | Welsh Carson | 23 | Financial Sponsor | Physician Groups |
| 6 | Warburg Pincus | 23 | Financial Sponsor | Home Health/Hospice |
| 7 | New Mountain Capital | 21 | Financial Sponsor | Behavioral Health |
| 8 | TPG Capital | 18 | Financial Sponsor | Health Insurance |
| 9 | Advent International | 18 | Financial Sponsor | Behavioral Health |
| 10 | KKR | 17 | Financial Sponsor | Physician Groups |
| 11 | Veritas Capital | 16 | Financial Sponsor | Home Health/Hospice |
| 12 | Hellman & Friedman | 15 | Financial Sponsor | Physician Groups |
| 13 | GTCR | 14 | Financial Sponsor | Dental |
| 14 | General Atlantic | 14 | Financial Sponsor | Physician Groups |
| 15 | Francisco Partners | 14 | Financial Sponsor | Medical Devices |
| 16 | VNS Health | 6 | Strategic | Home Health/Hospice |
| 17 | CenterWell Home Health | 6 | Strategic | Home Health/Hospice |
| 18 | Lyra Health | 5 | Strategic | Behavioral Health |
| 19 | Universal Health Services | 5 | Strategic | Behavioral Health |
| 20 | Amgen | 5 | Strategic | Pharma/Biotech |

This is exactly why `ranking.py`'s eligibility dampener exists: without it, deal-count-heavy PE funds would
dominate every shortlist regardless of actual fit, since raw deal volume alone favors them 3-5x over the most
active strategics.

## Reproducing this report

`data/profile_report.txt` is the raw output this document summarizes, generated by `python
scripts/profile_data.py`. Re-run it if the underlying CSV ever changes; this markdown version won't
auto-update.
