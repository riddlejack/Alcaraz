# Results

Log loss, lower is better. Every number in a table row is computed on the same matches:
primary targets present in every rung's forecast file and priced by the market. Intervals
are 95% percentile intervals from 2,000 match-level bootstrap draws stratified by year
(seed 20260912), conditional on the saved forecasts, without fitting or selection variance.
Values are rounded to four decimals. Seasons are robustness evidence, not replications.

The men's tables are the current version's, filled from
[current_2017_2025.json](benchmarks/current_2017_2025.json); the P1 rung was not rerun with
it and comes from [ladder.json](ladder.json) on the same matches. The women's tables are the
previous version's, from [ladder.json](ladder.json): the current version covers the men's tour
only. Comparisons with public models are in [benchmarks](benchmarks), the current version's
on [CURRENT_2017_2025_RESULTS.md](benchmarks/CURRENT_2017_2025_RESULTS.md).

## ATP, current version

Rungs:

- **elo**: the mean of the overall and surface Elo win probabilities from tour-level results;
  K 32, scale 400, two-day cutoff; no fit and no calibration.
- **atp_p0**: a histogram gradient-boosting classifier on match-history features (Elo, serve
  and return counts, workload, rankings, context), with past-only selection and calibration.
- **atp_p1**: P0 plus player traits and replayed dynamic serve/return states.
- **atp_full_tier**: P1 plus qualifying, Challenger and Futures history (tier-aware Elo,
  experience counts, tier serve/return states).
- **previous**: the previous version, full_tier plus entry status (Q, LL, WC, PR) and
  tournament level.
- **current**: Alcaraz, the previous version and the all-tier second model averaged in
  log-odds with equal weights fixed in advance.

### Per year

| year | n | elo | atp_p0 | atp_p1 | atp_full_tier | previous | current | pinnacle_normalised | pinnacle_calibrated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | 2,311 | 0.6124 | 0.6029 | 0.5984 | 0.5938 | 0.5917 | 0.5887 | 0.5875 | 0.5885 |
| 2018 | 2,587 | 0.6345 | 0.6200 | 0.6119 | 0.6044 | 0.6029 | 0.5998 | 0.5916 | 0.5915 |
| 2019 | 2,491 | 0.6279 | 0.6159 | 0.6113 | 0.6053 | 0.6061 | 0.6028 | 0.5944 | 0.5944 |
| 2020 | 1,241 | 0.6191 | 0.6093 | 0.6018 | 0.5953 | 0.5937 | 0.5907 | 0.5747 | 0.5748 |
| 2021 | 2,384 | 0.6273 | 0.6186 | 0.6080 | 0.5973 | 0.5962 | 0.5924 | 0.5905 | 0.5906 |
| 2022 | 2,525 | 0.6162 | 0.6058 | 0.5991 | 0.5926 | 0.5928 | 0.5886 | 0.5824 | 0.5822 |
| 2023 | 2,672 | 0.6267 | 0.6116 | 0.6050 | 0.5998 | 0.5973 | 0.5960 | 0.5874 | 0.5874 |
| 2024 | 2,671 | 0.6220 | 0.6108 | 0.6050 | 0.5968 | 0.5959 | 0.5931 | 0.5836 | 0.5833 |
| 2025 | 2,479 | 0.6339 | 0.6301 | 0.6257 | 0.6157 | 0.6136 | 0.6097 | 0.6025 | 0.6031 |
| **all, match-weighted** | 21,361 | **0.6249** | **0.6142** | **0.6077** | **0.6004** | **0.5993** | **0.5961** | **0.5890** | **0.5891** |
| all, equal-year mean | nine years | 0.6244 | 0.6139 | 0.6073 | 0.6001 | 0.5989 | 0.5958 | 0.5883 | 0.5884 |

### Paired contrasts (log loss delta, negative favours the first)

| contrast | match-weighted | equal-year | years negative | interval |
|---|---:|---:|---:|---:|
| elo_minus_atp_p0 | +0.0107 | +0.0106 | 0/9 | [+0.0086, +0.0129] |
| elo_minus_pinnacle_normalised | +0.0358 | +0.0362 | 0/9 | [+0.0328, +0.0389] |
| atp_p0_minus_atp_p1 | +0.0065 | +0.0065 | 0/9 | [+0.0049, +0.0080] |
| atp_p0_minus_atp_full_tier | +0.0138 | +0.0138 | 0/9 | [+0.0116, +0.0160] |
| atp_p0_minus_pinnacle_normalised | +0.0252 | +0.0256 | 0/9 | [+0.0225, +0.0277] |
| atp_p1_minus_atp_full_tier | +0.0073 | +0.0072 | 0/9 | [+0.0056, +0.0088] |
| atp_p1_minus_pinnacle_normalised | +0.0187 | +0.0191 | 0/9 | [+0.0163, +0.0210] |
| atp_full_tier_minus_previous | +0.0012 | +0.0012 | 2/9 | [+0.0006, +0.0017] |
| atp_full_tier_minus_pinnacle_normalised | +0.0114 | +0.0118 | 0/9 | [+0.0094, +0.0136] |
| previous_minus_current | +0.0031 | +0.0032 | 0/9 | [+0.0024, +0.0039] |
| previous_minus_pinnacle_normalised | +0.0102 | +0.0106 | 0/9 | [+0.0082, +0.0123] |
| current_minus_pinnacle_normalised | +0.0071 | +0.0075 | 0/9 | [+0.0053, +0.0089] |

The atp_p1 rows are the published ladder's. The other previous-version rows equal it to
twelve decimals on the same matches.

### Winner accuracy

A probability above one half picks player A and one below picks player B; an exact half is
a tie worth half credit. Accuracy was never a fitting or selection target.

| year | n | elo | atp_p0 | atp_full_tier | previous | current | pinnacle_normalised |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2017 | 2,311 | 66.5% | 67.0% | 66.8% | 67.4% | 67.1% | 68.0% |
| 2018 | 2,587 | 64.4% | 64.7% | 66.0% | 66.4% | 66.4% | 68.1% |
| 2019 | 2,491 | 64.0% | 64.8% | 66.0% | 66.2% | 67.0% | 67.3% |
| 2020 | 1,241 | 64.1% | 65.9% | 67.3% | 67.1% | 68.5% | 69.5% |
| 2021 | 2,384 | 63.1% | 64.3% | 67.0% | 66.9% | 67.9% | 68.2% |
| 2022 | 2,525 | 64.8% | 65.7% | 67.1% | 66.9% | 67.1% | 67.8% |
| 2023 | 2,672 | 64.8% | 65.6% | 66.3% | 66.7% | 66.4% | 67.6% |
| 2024 | 2,671 | 64.6% | 65.5% | 66.1% | 66.8% | 66.7% | 68.5% |
| 2025 | 2,479 | 62.9% | 64.3% | 65.5% | 65.6% | 66.2% | 67.1% |
| **all** | 21,361 | **64.4%** | **65.3%** | **66.4%** | **66.6%** | **66.9%** | **67.9%** |

## WTA, previous version: 2019–2025

Rungs: **elo** as above; **wta_base**, the boosted model on match-history features;
**wta_full**, plus traits and dynamic serve/return states; **wta_full_entry**, plus entry
status and tournament level (the previous version on the women's tour).

| year | n | elo | wta_base | wta_full | wta_full_entry | pinnacle_normalised | pinnacle_calibrated |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019 | 2,317 | 0.6341 | 0.6231 | 0.6190 | 0.6178 | 0.6002 | 0.6000 |
| 2020 | 1,013 | 0.6281 | 0.6184 | 0.6173 | 0.6145 | 0.6039 | 0.6039 |
| 2021 | 2,321 | 0.6165 | 0.6072 | 0.6013 | 0.6008 | 0.5756 | 0.5747 |
| 2022 | 2,307 | 0.6301 | 0.6171 | 0.6134 | 0.6113 | 0.5915 | 0.5918 |
| 2023 | 2,439 | 0.6224 | 0.6182 | 0.6122 | 0.6122 | 0.5903 | 0.5903 |
| 2024 | 2,388 | 0.6253 | 0.6117 | 0.6054 | 0.6043 | 0.5884 | 0.5882 |
| 2025 | 2,243 | 0.6277 | 0.6237 | 0.6161 | 0.6160 | 0.5965 | 0.5964 |
| **all, match-weighted** | 15,028 | **0.6261** | **0.6169** | **0.6116** | **0.6106** | **0.5913** | **0.5911** |
| all, equal-year mean | seven years | 0.6263 | 0.6171 | 0.6121 | 0.6110 | 0.5923 | 0.5922 |

| contrast | match-weighted | equal-year | years negative | interval |
|---|---:|---:|---:|---:|
| elo_minus_wta_base | +0.0092 | +0.0092 | 0/7 | [+0.0067, +0.0116] |
| elo_minus_pinnacle_normalised | +0.0348 | +0.0340 | 0/7 | [+0.0313, +0.0386] |
| wta_base_minus_wta_full | +0.0053 | +0.0050 | 0/7 | [+0.0038, +0.0069] |
| wta_base_minus_pinnacle_normalised | +0.0256 | +0.0247 | 0/7 | [+0.0226, +0.0289] |
| wta_full_minus_wta_full_entry | +0.0010 | +0.0011 | 1/7 | [+0.0002, +0.0017] |
| wta_full_minus_pinnacle_normalised | +0.0203 | +0.0198 | 0/7 | [+0.0173, +0.0233] |
| wta_full_entry_minus_pinnacle_normalised | +0.0194 | +0.0187 | 0/7 | [+0.0165, +0.0223] |

## WTA, previous version: 2025–2026 bridge window

The same rungs without the entry-status block, on the 2025–2026 window. That window is
spent development evidence, not a holdout.

| year | n | elo | wta_base | wta_full | pinnacle_normalised | pinnacle_calibrated |
|---|---:|---:|---:|---:|---:|---:|
| 2025 | 2,243 | 0.6277 | 0.6237 | 0.6161 | 0.5965 | 0.5964 |
| 2026 | 101 | 0.6003 | 0.6082 | 0.5985 | 0.5698 | 0.5682 |
| **all, match-weighted** | 2,344 | **0.6265** | **0.6230** | **0.6153** | **0.5953** | **0.5952** |
| all, equal-year mean | two years | 0.6140 | 0.6160 | 0.6073 | 0.5831 | 0.5823 |

| contrast | match-weighted | equal-year | years negative | interval |
|---|---:|---:|---:|---:|
| elo_minus_wta_base | +0.0035 | −0.0020 | 1/2 | [−0.0029, +0.0094] |
| elo_minus_pinnacle_normalised | +0.0312 | +0.0308 | 0/2 | [+0.0224, +0.0402] |
| wta_base_minus_wta_full | +0.0077 | +0.0087 | 0/2 | [+0.0032, +0.0122] |
| wta_base_minus_pinnacle_normalised | +0.0277 | +0.0328 | 0/2 | [+0.0200, +0.0356] |
| wta_full_minus_pinnacle_normalised | +0.0200 | +0.0241 | 0/2 | [+0.0127, +0.0279] |

## Research degrees of freedom

The previous version's archive holds 145 leaderboard entries, 130 of them on cohorts
naming a year in 2017–2024, and 133 experiment-ledger entries
([data/registries](../data/registries)). Every entry is an exposed pass over
development data; nothing on disk is a holdout. The current version's passes are listed on
[CURRENT_2017_2025_RESULTS.md](benchmarks/CURRENT_2017_2025_RESULTS.md).
