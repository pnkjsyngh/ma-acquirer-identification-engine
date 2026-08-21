# Target Sensitivity

Sanity check: does the ranking actually move with the target, or does it default to the same acquirers
regardless of input? Computed directly from `rank_acquirers()` (deterministic, no LLM) against all 10 profiles
in `data/synthetic_profiles.json`, top-10 overlap measured against the `healthcare_services_default` profile.

| Profile | Sector (~EV) | Overlap w/ default | Type mix (top 10) | Top 3 |
|---|---|---|---|---|
| `healthcare_services_default` | Healthcare Services ~$200M | 10/10 (baseline) | 4 Strategic / 6 FinSponsor | Atrium Health, UPMC, Steward Health Care |
| `health_it_national` | Health IT ~$150M | 0/10 | 8 Strategic / 2 FinSponsor | Veeva Systems, Ciox Health, Evolent Health |
| `medical_devices_midwest` | Medical Devices ~$300M | 3/10 | 5 Strategic / 5 FinSponsor | Medtronic, Boston Scientific, Francisco Partners |
| `dental_southeast` | Dental ~$80M | 3/10 | 4 Strategic / 6 FinSponsor | Dental365, Aspen Dental (ADMI), Heartland Dental |
| `behavioral_health_mountain_west` | Behavioral Health ~$250M | 3/10 | 6 Strategic / 4 FinSponsor | LifeStance Health, Behavioral Health Group, Talkspace |
| `home_health_southeast` | Home Health/Hospice ~$120M | 2/10 | 7 Strategic / 3 FinSponsor | CenterWell Home Health, VNS Health, Enhabit |
| `physician_groups_northeast` | Physician Groups ~$180M | 5/10 | 2 Strategic / 8 FinSponsor | Aspen Dental (ADMI), Nordic Capital, GTCR |
| `revenue_cycle_national` | Revenue Cycle ~$90M | 1/10 | 6 Strategic / 4 FinSponsor | Conifer Health, Ensemble Health Partners, Waystar |
| `health_insurance_multi_regional` | Health Insurance ~$350M | 1/10 | 3 Strategic / 7 FinSponsor | Alignment Healthcare, Centene, Molina Healthcare |
| `pharma_biotech_west_coast` | Pharma/Biotech ~$220M | 2/10 | 7 Strategic / 3 FinSponsor | Bristol-Myers Squibb, Amgen, Gilead Sciences |

## Reading this

- **Overlap ranges 0-5 out of 10** across the 9 non-default profiles — the ranking genuinely moves with the
  target rather than surfacing the same acquirers regardless of input. `health_it_national` shares zero
  acquirers with the default; `physician_groups_northeast` shares the most (5), which makes sense given
  Physician Groups is one of the sectors closest to Healthcare Services in the data-derived adjacency measure.
- **Acquirer-type mix varies by sector**, not fixed at some constant ratio — Health IT and Home Health/Hospice
  skew heavily Strategic (8/2 and 7/3), while Physician Groups and Health Insurance skew heavily Financial
  Sponsor (2/8 and 3/7). This reflects real dataset structure (see `data/profile_report.txt`: PE dominance
  concentrates in certain sectors), not an artifact of the ranking formula.
- **`Aspen Dental (ADMI)` appears in both `dental_southeast` and `physician_groups_northeast`'s top 3** — a
  cross-sector buyer this data-derived, no hand-tuned prior, expected: the whole point of the cosine-similarity
  sector-adjacency measure (see `docs/architecture.md`) is to surface exactly this kind of real buyer overlap
  between related sectors.
