# BuildOak comparison extended to 2025: ATP 2017–2025 and WTA 2019–2025 (EXT2025)

> **2025 is exposed retrospective data, not a holdout.** It was inspected before the model
> freeze (archive decision D134) and scored by REFIT2025 (D137, D138). The accepted results
> remain the registered claims, and each extended number is shown beside its registered
> one: [ATP 2017–2024](BUILDOAK_2017_2024_RESULTS.md), archive decisions D131 and D132; [WTA 2019–2024](BUILDOAK_WTA_2019_2024_RESULTS.md), D133.
> Acceptance of this extension: decision pending, independent reconstruction ACCEPT.

Every number on this page is filled from [buildoak_2017_2025.json](buildoak_2017_2025.json),
[buildoak_wta_2019_2025.json](buildoak_wta_2019_2025.json) and the two accepted JSONs by
`tools/check_readme_numbers.py`; the JSONs are built from the archive scorer outputs by
`tools/build_benchmark_aggregates.py`.

## What changed from the accepted comparison

- **One Alcaraz arm, the frozen model.** Alcaraz is `full_tier_entry` on
  the men's tour and `full_entry` on the women's tour (D134): the
  accepted forecasts for the earlier seasons and the REFIT2025 forecasts for 2025. The
  previous version is bound for the record and not scored. The scorer, seed, draws and
  block lengths are the accepted ones (design amendment A3).
- **One more BuildOak fit.** BuildOak was fitted once more, at the 2024-12-30 boundary,
  with the frozen adaptation in the same container; its 2025 forecasts were used only after
  the accepted 2024 BuildOak runs reproduced byte for byte there (A1; men
  BYTE_IDENTICAL, women
  BYTE_IDENTICAL).
- **A structural break in the rival.** ATP 2025 is the first ATP season in which the frozen adapter activates its recent-era model: 15,959 recent rows (from 2019-01-01) against its frozen threshold of 15,000, so every one of the 2,589 2025 targets gets 0.8 of the full model plus 0.2 of the recent model (A1); the 2017-2024 forecasts never used it, so the 2025 BuildOak forecasts come from a structurally different recipe.
  On the women's tour, the recent-era blend is inactive in 2019-2023 and active in 2024 (accepted WTA record) and in 2025: 20,353 recent rows (from 2017-01-01) against the frozen threshold of 15,000, weight 0.35 on the recent model for all 2,351 2025 targets; the pooled contrasts mix both regimes.
- **No gates.** EXT2025 fixed what is reported before any extended score existed; every
  number is reported whatever it shows, and the 2025-only difference is descriptive, not a
  separate test.
- **Accepted seasons unchanged.** Before writing the extended JSON, the builder checks that
  every accepted season's counts, per-season scores, per-season differences, blend weights
  and BuildOak forecast files equal the accepted result exactly.

## Men's tour, 2017–2025

| | Extended (EXT2025) | Registered (accepted) |
|---|---:|---:|
| Seasons | 2017–2025 | 2017–2024 |
| Matches | 21,561 | 18,972 |
| Alcaraz log loss, match-weighted | 0.5991 | 0.5976 |
| BuildOak log loss, match-weighted | 0.6058 | 0.6046 |
| Alcaraz − BuildOak, paired log loss | −0.0067 | −0.0070 |
| 95% interval, eight-week blocks (primary) | [−0.0095, −0.0041] | [−0.0100, −0.0040] |
| 95% interval, four-week blocks | [−0.0094, −0.0041] | [−0.0098, −0.0043] |
| 95% interval, thirteen-week blocks | [−0.0096, −0.0039] | [−0.0100, −0.0040] |
| Equal-year mean difference | −0.0066 [−0.0089, −0.0044] | −0.0068 [−0.0092, −0.0044] |
| Seasons with Alcaraz ahead | 8 of 9 | 7 of 8 |
| Alcaraz − normalised Pinnacle, priced matches (descriptive) | +0.0102 [+0.0081, +0.0123] on 21,361 | +0.0101 [+0.0078, +0.0125] on 18,882 |

Paired log loss, left minus right, on identical matches; negative favours Alcaraz. Intervals
are 95% percentile intervals from 5,000 stationary
calendar-week bootstrap draws (seed 20260922); the extended
interval shares its first seasons with the registered one and is not an independent
confirmation.

| Season | Matches | Alcaraz | BuildOak | Alcaraz − BuildOak |
|---|---:|---:|---:|---:|
| 2017 | 2,323 | 0.5915 | 0.5993 | −0.0078 |
| 2018 | 2,606 | 0.6035 | 0.6101 | −0.0066 |
| 2019 | 2,502 | 0.6064 | 0.6150 | −0.0085 |
| 2020 | 1,250 | 0.5936 | 0.5971 | −0.0035 |
| 2021 | 2,390 | 0.5965 | 0.6086 | −0.0121 |
| 2022 | 2,538 | 0.5920 | 0.5905 | +0.0015 |
| 2023 | 2,682 | 0.5987 | 0.6118 | −0.0131 |
| 2024 | 2,681 | 0.5956 | 0.6000 | −0.0045 |
| 2025 | 2,589 | 0.6103 | 0.6150 | −0.0047 |

Per-season match-weighted log loss. The rows before 2025 equal the accepted page.

### Blend, descriptive

The accepted past-only blend rule, extended by one target year: blend logit =
(1 − w)·logit(Alcaraz) + w·logit(BuildOak), with w chosen on the grid
0.00 to 0.50 over the three
preceding target years and never the target year.

| Target year | Weight on BuildOak | Fitted on | Matches in fit | Role |
|---|---:|---|---:|---|
| 2018 | 0.30 | 2017 | 2,323 | secondary_short_lookback |
| 2019 | 0.30 | 2017–2018 | 4,929 | secondary_short_lookback |
| 2020 | 0.25 | 2017–2019 | 7,431 | primary |
| 2021 | 0.30 | 2018–2020 | 6,358 | primary |
| 2022 | 0.20 | 2019–2021 | 6,142 | primary |
| 2023 | 0.35 | 2020–2022 | 6,178 | primary |
| 2024 | 0.25 | 2021–2023 | 7,610 | primary |
| 2025 | 0.30 | 2022–2024 | 7,901 | primary |

On the 14,130 primary matches
(2020–2025), blend − Alcaraz is
−0.0011
[−0.0021, −0.0000] and blend − BuildOak
−0.0073
[−0.0101, −0.0046]. Registered
(2020–2024,
11,541 matches):
−0.0009
[−0.0021, +0.0003] and
−0.0076
[−0.0107, −0.0043].

The registered 2020–2024 test is the claim and stays so: its interval for blend − Alcaraz
included zero, the blend was not adopted, and no blend is released; the model is frozen
(D134). With 2025 added, the interval touches zero: its upper bound is
−0.00002 under the registered seed,
and under twenty alternative seeds it is below zero only
five times (independent reconstruction). This is a
descriptive reading of one more exposed season, not a pass, and it changes neither decision.

## Women's tour, 2019–2025

| | Extended (EXT2025) | Registered (accepted) |
|---|---:|---:|
| Seasons | 2019–2025 | 2019–2024 |
| Matches | 15,251 | 12,900 |
| Alcaraz log loss, match-weighted | 0.6102 | 0.6092 |
| BuildOak log loss, match-weighted | 0.6121 | 0.6118 |
| Alcaraz − BuildOak, paired log loss | −0.0019 | −0.0026 |
| 95% interval, eight-week blocks (primary) | [−0.0050, +0.0009] | [−0.0058, +0.0004] |
| 95% interval, four-week blocks | [−0.0048, +0.0009] | [−0.0058, +0.0004] |
| 95% interval, thirteen-week blocks | [−0.0049, +0.0009] | [−0.0059, +0.0004] |
| Equal-year mean difference | −0.0019 [−0.0043, +0.0004] | −0.0025 [−0.0049, −0.0000] |
| Seasons with Alcaraz ahead | 4 of 7 | 4 of 6 |

The accepted women's comparison was registered as underpowered, and its interval included
zero; the extension adds one season and is read the same way. The equal-year interval now
includes zero as well, [−0.0043, +0.0004]; the accepted 2019–2024 one did not,
[−0.0049, −0.00004].

| Season | Matches | Alcaraz | BuildOak | Alcaraz − BuildOak |
|---|---:|---:|---:|---:|
| 2019 | 2,337 | 0.6177 | 0.6251 | −0.0074 |
| 2020 | 1,019 | 0.6138 | 0.6148 | −0.0009 |
| 2021 | 2,363 | 0.6000 | 0.5978 | +0.0022 |
| 2022 | 2,324 | 0.6110 | 0.6183 | −0.0074 |
| 2023 | 2,453 | 0.6127 | 0.6120 | +0.0007 |
| 2024 | 2,404 | 0.6028 | 0.6050 | −0.0022 |
| 2025 | 2,351 | 0.6153 | 0.6136 | +0.0017 |

On the 9,532 primary blend matches
(2022–2025), blend − Alcaraz is
−0.0027
[−0.0039, −0.0014] and blend − BuildOak
−0.0044
[−0.0065, −0.0024]; the registered
release of the women's blend as a research artefact (D133) rests on the accepted
2022–2024 result, not on this
extension.

## Limits

- An exposed retrospective comparison of complete systems with different legitimate
  histories; not an untouched test, prospective evidence or a market claim.
- The men's 2025 BuildOak forecasts come from a structurally different recipe than the
  earlier seasons (A1); the pooled contrast mixes both. On the women's tour the recent-era
  recipe runs in 2024 and 2025 only.
- Independent reconstruction of both tours: ACCEPT (men),
  ACCEPT (women); the decision entry is
  pending.
- BuildOak's recipe was selected by its author on ROC AUC with sight of 2026 data.
- The intervals condition on the saved forecasts and omit refit, selection and
  source-choice uncertainty.

Machine-readable aggregates, per-season tables, blend grids, draw hashes and provenance:
[buildoak_2017_2025.json](buildoak_2017_2025.json),
[buildoak_wta_2019_2025.json](buildoak_wta_2019_2025.json).
