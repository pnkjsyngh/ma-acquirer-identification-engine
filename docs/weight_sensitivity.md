# Weight Sensitivity

How the top-10 acquirer ranking for the default profile (`Healthcare Services`, ~$200M) moves under per-weight perturbation of `app.features.WEIGHTS`, each delta renormalized so weights sum to 1.0.

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

## Reading this

Across all 24 perturbations, top-10 overlap ranged 8/10 to 10/10 and Spearman rho ranged 0.791 to 0.973. The ranking is most sensitive to `sector_fit` (mean overlap 9.2/10, mean rho 0.892) -- moving it reorders the top 10 the most -- and most robust to `tag_alignment` (mean overlap 10.0/10, mean rho 0.933).
