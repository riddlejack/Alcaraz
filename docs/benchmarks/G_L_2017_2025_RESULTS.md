# Ranking and Elo baselines extended to 2025: ATP 2017–2025, WTA 2019–2025 (EXT2025)

> **2025 is exposed retrospective data, not a holdout.** It was inspected before the model
> freeze (archive decision D134) and scored by REFIT2025 (D137, D138). The accepted results
> remain the registered claims, and each extended number is shown beside its registered
> one: [G_L_RESULTS.md](G_L_RESULTS.md), ATP 2017–2024 and WTA 2019–2024.
> Accepted as archive decision D139, independently reconstructed.

The frozen G-L procedure was run twice with the season range extended (design amendment
A2), each run once: **(b)** with the frozen model as the Tennis Lab row (ATP
`full_tier_entry`, WTA `full_entry`), the published extended row, and **(a)** with the
version the accepted comparison used (ATP `full_tier`, WTA `full`), whose earlier seasons
equal the accepted report value for value. Every number below is filled from
[G_L_RESULTS_2017_2025.json](G_L_RESULTS_2017_2025.json) (b),
[G_L_RESULTS_2017_2025_continuity.json](G_L_RESULTS_2017_2025_continuity.json) (a) and the
accepted [G_L_RESULTS.json](G_L_RESULTS.json).

Men: 21,561 ATP matches (registered 18,972).
Women: 15,251 WTA matches (registered 12,900).
Each season has equal weight; earlier seasons set each baseline's calibration, as before.

| Model, equal-year log loss | ATP extended (b) | ATP registered | WTA extended (b) | WTA registered |
|---|---:|---:|---:|---:|
| Tennis Lab (frozen model / accepted version) | 0.5987 | 0.5984 | 0.6105 | 0.6111 |
| Pooled Elo (K=32) | 0.6229 | 0.6222 | 0.6253 | 0.6255 |
| Ranking-based logistic model | 0.6334 | 0.6334 | 0.6378 | 0.6381 |
| Kovalchik overall/major Elo reconstruction | 0.6272 | 0.6268 | 0.6232 | 0.6229 |
| FiveThirtyEight surface-Elo adaptation | 0.6237 | 0.6230 | 0.6216 | 0.6212 |
| Weighted Elo (WElo) reconstruction | 0.6264 | 0.6261 | 0.6232 | 0.6233 |

The registered Tennis Lab row is the accepted version (ATP `full_tier`, WTA `full`); the
extended row is the frozen model.

## Paired differences with simultaneous intervals

Tennis Lab minus each baseline, equal-year log loss, 95% simultaneous intervals over the
five comparisons with eight-week calendar blocks; the last column is the 2025 season alone
(descriptive).

### Men

| Baseline | Extended (b) | Continuity (a) | Registered | 2025 alone (b) |
|---|---:|---:|---:|---:|
| Pooled Elo (K=32) | −0.0242 [−0.0275, −0.0209] | −0.0230 [−0.0262, −0.0198] | −0.0239 [−0.0274, −0.0203] | −0.0176 |
| Ranking-based logistic model | −0.0347 [−0.0384, −0.0310] | −0.0335 [−0.0372, −0.0298] | −0.0351 [−0.0390, −0.0311] | −0.0226 |
| Kovalchik overall/major Elo reconstruction | −0.0285 [−0.0326, −0.0245] | −0.0273 [−0.0314, −0.0233] | −0.0285 [−0.0329, −0.0240] | −0.0201 |
| FiveThirtyEight surface-Elo adaptation | −0.0250 [−0.0284, −0.0215] | −0.0238 [−0.0271, −0.0204] | −0.0246 [−0.0283, −0.0209] | −0.0190 |
| Weighted Elo (WElo) reconstruction | −0.0277 [−0.0317, −0.0237] | −0.0265 [−0.0304, −0.0225] | −0.0277 [−0.0321, −0.0233] | −0.0184 |

### Women

| Baseline | Extended (b) | Continuity (a) | Registered | 2025 alone (b) |
|---|---:|---:|---:|---:|
| Pooled Elo (K=32) | −0.0148 [−0.0177, −0.0120] | −0.0137 [−0.0167, −0.0107] | −0.0144 [−0.0175, −0.0114] | −0.0090 |
| Ranking-based logistic model | −0.0273 [−0.0311, −0.0235] | −0.0261 [−0.0301, −0.0222] | −0.0271 [−0.0313, −0.0228] | −0.0204 |
| Kovalchik overall/major Elo reconstruction | −0.0127 [−0.0153, −0.0101] | −0.0115 [−0.0141, −0.0089] | −0.0118 [−0.0145, −0.0091] | −0.0098 |
| FiveThirtyEight surface-Elo adaptation | −0.0111 [−0.0135, −0.0087] | −0.0100 [−0.0124, −0.0075] | −0.0102 [−0.0127, −0.0076] | −0.0086 |
| Weighted Elo (WElo) reconstruction | −0.0127 [−0.0154, −0.0100] | −0.0115 [−0.0142, −0.0088] | −0.0122 [−0.0149, −0.0095] | −0.0074 |

## Limits

The intervals condition on the fitted forecasts and the week-based dependence model. The
comparison evaluates complete systems with different inputs, as before. The extension
shares its earlier seasons with the registered comparison and is not an independent
confirmation; a changed sign in any interval would be reported here whatever it showed.
