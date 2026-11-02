# Alcaraz, current version: ATP 2017–2025

The current version of Alcaraz is the previous version averaged with a second, differently
built model: for every match it takes the mean of the two models' log-odds, with equal
weights fixed before any test, `p = σ(½·logit(previous) + ½·logit(second))`. Nothing in it
is refitted on test seasons. It covers the men's tour only; every women's-tour result in
this repository is the previous version's.

Every number on this page is filled from [current_2017_2025.json](current_2017_2025.json),
which `tools/build_benchmark_aggregates.py` builds from the research result files named and
hash-pinned in [sources.json](sources.json). The previous version's P1 rung comes from
[ladder.json](../ladder.json) and [winner_accuracy.json](../winner_accuracy.json), and the
previous version's UTS and Ingram rows from
[uts_ingram_2024_2025.json](uts_ingram_2024_2025.json).

These are retrospective results. Every season from 2017 to 2024 had been scored for the
previous version before the second model was built, and the second model was developed
on 2017–2021. Three later checks were registered before their forecasts existed: 2024,
2015–2016 and 2025. Each is reported below with what it showed.

## How the comparisons were scored

- **Paired.** Both forecasts are scored on exactly the same matches, and the page reports
  left minus right in log loss: a negative difference favours Alcaraz. Each comparison has
  its own rows, stated beside it.
- **Intervals against public models.** 5,000 draws of a stationary
  calendar-week block bootstrap with a mean block of 8 weeks (seed
  20260922); blocks of 4 and 13 weeks are reported as checks. Matches in the same
  week share players and conditions, so whole weeks are resampled together.
- **Intervals on the ladder and the market gap.** 2,000 match-level bootstrap
  draws stratified by season (seed 20260912), as in the published ladder.
- **Conditional on the saved forecasts.** No interval includes the variance of fitting,
  selection or calibration.

## The ladder

The same 21,361 ATP matches, 2017–2025, each with a Pinnacle price.

| Model | Log loss | Correct picks |
|---|---:|---:|
| Elo only, no fitting | 0.6249 | 64.4% |
| + boosted model on results, rankings and workload | 0.6142 | 65.3% |
| + player traits and dynamic serve/return states | 0.6077 | 66.0% |
| + qualifying, Challenger and Futures history | 0.6004 | 66.4% |
| + entry status and tournament level: the previous version | 0.5993 | 66.6% |
| **Averaged with the second model: Alcaraz** | **0.5961** | **66.9%** |
| Pinnacle closing price, normalised | 0.5890 | 67.9% |

| Contrast | 2017–2025 | 2017–2024 | 2025 |
|---|---:|---:|---:|
| Alcaraz − previous version | −0.0031 [−0.0039, −0.0024] | −0.0031 [−0.0039, −0.0022] | −0.0039 [−0.0061, −0.0017] |
| Alcaraz − Pinnacle | +0.0071 [+0.0053, +0.0089] | +0.0071 [+0.0051, +0.0089] | +0.0072 [+0.0015, +0.0128] |
| Previous version − Pinnacle | +0.0102 [+0.0082, +0.0123] | +0.0101 [+0.0080, +0.0122] | +0.0111 [+0.0047, +0.0176] |
| Matches | 21,361 | 18,882 | 2,479 |
| Correct picks: Alcaraz, Pinnacle | 66.9%, 67.9% | 67.0%, 68.0% | 66.2%, 67.1% |

Alcaraz is ahead of the previous version in 9 of 9 seasons and behind
Pinnacle in 9 of 9. The P1 rung was not rerun on this pass; its
row is the published one on the same matches, and the other rungs of the previous version
equal the published ladder to twelve decimals.

| Season | Matches | Previous version | Alcaraz | Pinnacle | Alcaraz − previous |
|---|---:|---:|---:|---:|---:|
| 2017 | 2,311 | 0.5917 | 0.5887 | 0.5875 | −0.0030 |
| 2018 | 2,587 | 0.6029 | 0.5998 | 0.5916 | −0.0031 |
| 2019 | 2,491 | 0.6061 | 0.6028 | 0.5944 | −0.0033 |
| 2020 | 1,241 | 0.5937 | 0.5907 | 0.5747 | −0.0031 |
| 2021 | 2,384 | 0.5962 | 0.5924 | 0.5905 | −0.0038 |
| 2022 | 2,525 | 0.5928 | 0.5886 | 0.5824 | −0.0042 |
| 2023 | 2,672 | 0.5973 | 0.5960 | 0.5874 | −0.0013 |
| 2024 | 2,671 | 0.5959 | 0.5931 | 0.5836 | −0.0028 |
| 2025 | 2,479 | 0.6136 | 0.6097 | 0.6025 | −0.0039 |

## Against BuildOak on the same files and timing rule

[BuildOak](https://github.com/buildoak/tennis-xgboost-autoresearch) is the strongest public
model that could be reproduced. Here it is given the same lower-tier files as Alcaraz and
the same timing rule: a result becomes usable two days after its match date, and no
setting is taken from the future. Rows are the target matches both systems cover.

| Period | Matches | Alcaraz − BuildOak | Previous version − BuildOak | Seasons Alcaraz ahead |
|---|---:|---:|---:|---:|
| 2017–2025 | 21,521 | **−0.0038 [−0.0056, −0.0020]** | −0.0006 [−0.0027, +0.0014] | 8 of 9 |
| 2017–2024 | 18,962 | −0.0035 [−0.0054, −0.0016] | −0.0004 [−0.0027, +0.0017] | 7 of 8 |
| 2024 alone | 2,679 | +0.0021 [−0.0016, +0.0060] | +0.0049 [+0.0001, +0.0099] | 0 of 1 |
| 2025 alone, bug fixed | 2,559 | −0.0062 [−0.0110, −0.0018] | −0.0023 [−0.0072, +0.0023] | 1 of 1 |
| 2025 alone, registered pass | 2,559 | −0.0050 [−0.0111, +0.0008] | unchanged | 1 of 1 |

| | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Alcaraz − BuildOak | −0.0032 | −0.0033 | −0.0045 | −0.0071 | −0.0022 | −0.0026 | −0.0090 | +0.0021 | −0.0062 |

2024 was the season registered as the confirmation, and BuildOak edged Alcaraz in it,
inside the interval. The four- and thirteen-week block
checks for 2017–2025 give [−0.0056, −0.0021] and [−0.0055, −0.0020]. The second
model alone is −0.0037 [−0.0055, −0.0019] against BuildOak over 2017–2025;
the previous version alone is level with it.

### The timing rule and what BuildOak's own setup was worth

Historical files give tournament weeks, not exact match days, and results reach the public
with a lag. So a forecast may use only results from at least two days before its match. BuildOak's
own setup used results at once and dated each lower-tier result on the Sunday of its week,
so a Challenger result could reach the next tour event from its first match. Measured on
2017–2024, with BuildOak on the same lower-tier files throughout:

| Change to BuildOak (fair minus its own setup) | Matches | Log loss change |
|---|---:|---:|
| Same timing rule and settings as Alcaraz | 18,962 | +0.0024 [+0.0010, +0.0038] |
| The two-day rule alone | 18,962 | +0.0022 [+0.0006, +0.0038] |
| The rest: rating-recency reference and nationality buckets | 18,962 | +0.0002 [−0.0003, +0.0008] |
| Main-tour files only, same change | 18,962 | +0.0002 [−0.0008, +0.0013] |

A positive change means BuildOak scores worse under the fair rule: its own setup was worth
about that much to it, almost all of it through seeing lower-tier results a few days
sooner. On main-tour files alone the setup is worth nothing. Exact match days would help
both models equally; they are public only in part, so both sides run on the same
conservative rule.

### 2025, with its bug

The 2025 test was written down before any 2025 forecast existed and scored once. It ran
on a defective input. When the second model chose its 2025 settings from 2022–2024, the
file it read had 2024's results blanked, a leftover from when 2024 was sealed. Every
selection row for 2024 carried an invalid label, so it chose badly and its 2025 forecasts
were squashed toward 50/50. No 2025 result reached any model. The independent
recomputation caught the defect; the fix changed nothing but restoring the 2024 labels.

| 2025, 2,559 matches | Registered pass (defective input) | Bug fixed |
|---|---:|---:|
| Alcaraz − BuildOak | −0.0050 [−0.0111, +0.0008] | −0.0062 [−0.0110, −0.0018] |
| Holm-adjusted p | 0.099 | 0.008 |
| Alcaraz − previous version | −0.0027 [−0.0053, −0.0002] | −0.0038 [−0.0053, −0.0024] |
| Second model − previous version | +0.0057 [+0.0003, +0.0110] | −0.0047 [−0.0075, −0.0019] |
| Alcaraz − BuildOak, 2017–2025 | −0.0037 [−0.0056, −0.0018] | −0.0038 [−0.0056, −0.0020] |

The registered pass read level against BuildOak. With the bug fixed, Alcaraz wins 2025.
The corrected run came after the registered result had been seen, so it is the model's
correct 2025 number but not a blind confirmation. The 2017–2025 result does not depend on
the fix. In the defective run the second model alone was worse than the previous version,
yet the average still beat the previous version, because half its weight sat on a model
the bug did not touch. The rule that came out of it: every forecast generator now asserts
a valid label on every selection row before it selects anything.

### 2014–2016, never scored before

No forecast of these models or of BuildOak had been scored on these seasons. Challenger
serve statistics begin in 2010 and the models need six warm-up seasons, so 2014 is the
earliest season the second model reaches, and 2015 the earliest for the average.

| Contrast | Seasons | Matches | Log loss difference |
|---|---|---:|---:|
| Second model − BuildOak | 2014–2016 | 7,131 | −0.0029 [−0.0053, −0.0006] |
| Alcaraz − BuildOak | 2015–2016 | 4,806 | −0.0023 [−0.0051, +0.0003] |
| Previous version − BuildOak | 2015–2016 | 4,806 | +0.0012 [−0.0027, +0.0047] |
| Alcaraz − previous version | 2015–2016 | 4,806 | −0.0035 [−0.0047, −0.0020] |

Alcaraz is ahead on 2015–2016 but within the margin; the second model, which reaches one
more season, beats BuildOak over 2014–2016. These seasons are unscored but not untouched:
the second model's design was chosen on 2017–2021 outcomes.

## Other public models

Each row is its own paired comparison on the rows both sides cover.

| Public model | Matches | Alcaraz − model | Previous version − model |
|---|---|---:|---:|
| [BuildOak](https://github.com/buildoak/tennis-xgboost-autoresearch) as released: its own data and setup | 21,521, 2017–2025 | **−0.0083 [−0.0105, −0.0060]** | −0.0051 [−0.0076, −0.0027] |
| — 2025 alone | 2,559 | −0.0086 [−0.0154, −0.0018] | −0.0048 [−0.0117, +0.0022] |
| [tennis-ai](https://github.com/hikmatazimzade/tennis-ai) CatBoost, refitted each season on its author's table | 18,888, 2017–2024 | **−0.0124 [−0.0155, −0.0092]** | −0.0094 [−0.0125, −0.0061] |
| tennis-ai CatBoost given our lower-tier files | 18,888, 2017–2024 | **−0.0087 [−0.0112, −0.0061]** | −0.0057 [−0.0084, −0.0029] |
| — 2024 alone | 2,672 | −0.0022 [−0.0073, +0.0026] | |
| tennis-ai CatBoost as shipped (its checkpoint) | 2,528, 2025 | **−0.0084 [−0.0133, −0.0035]** | −0.0046 [−0.0093, −0.0001] |
| tennis-ai CatBoost refitted through 2024 | 2,528, 2025 | −0.0080 [−0.0133, −0.0032] | −0.0042 [−0.0095, +0.0006] |
| [tennis_elo](https://github.com/yaobviously/tennis_elo) ridge and LightGBM stack, look-ahead removed | 13,883, 2017–2023 | **−0.0081 [−0.0104, −0.0059]** | −0.0046 [−0.0069, −0.0024] |
| FiveThirtyEight surface-Elo adaptation | 21,521, 2017–2025 | −0.0280 [−0.0315, −0.0247] | −0.0248 [−0.0283, −0.0214] |
| Pooled Elo (K=32) | 21,521, 2017–2025 | −0.0274 [−0.0308, −0.0241] | −0.0242 [−0.0277, −0.0209] |
| Kovalchik overall/major Elo reconstruction | 21,521, 2017–2025 | −0.0314 [−0.0353, −0.0277] | −0.0282 [−0.0320, −0.0245] |
| Ranking-based logistic model | 21,521, 2017–2025 | −0.0376 [−0.0411, −0.0341] | −0.0344 [−0.0380, −0.0310] |
| Weighted Elo (WElo) reconstruction | 21,521, 2017–2025 | −0.0307 [−0.0347, −0.0269] | −0.0275 [−0.0315, −0.0237] |
| [Ultimate Tennis Statistics](https://github.com/mcekovic/tennis-crystal-ball) formula | 5,270, 2024–2025 | not rerun | −0.0248 [−0.0309, −0.0191] |
| [Ingram's Bayesian point model](https://github.com/martiningram/tennis_bayes_point_based) | 5,270, 2024–2025 | not rerun | −0.0443 [−0.0519, −0.0367] |

BuildOak as released runs on its own main-tour files with its own setup, so this row
compares complete systems with different data, unlike the fair comparison above. The
stack is rerun from its author's notebook with its look-ahead removed (qualifying rounds
ordered before the main draw, rolling windows closed on the right, career statistics made
expanding); its rows end in February 2023, where its data ends.

### Ultimate Tennis Statistics and Ingram

These two were not rerun for the current version: their saved forecasts were not
restored for this pass. The rows above are the previous version's published results.
A current-version figure can be derived without a rerun. On the same rows the previous
version's log loss reproduces its published value exactly, so the current version's log
loss on those rows minus each rival's published log loss is exact as a point estimate.
Its interval can only be a bound (the published half-width widened by the uncertainty of
the current-minus-previous step), not a bootstrap, because the rivals' forecasts are not
on hand to resample. That derived figure is not part of the scored result files, so it
is not shown here.

### What favours the rivals

Two integrity findings, both in the rivals' favour, so both make Alcaraz's wins
conservative:

- **tennis-ai's CatBoost reads later rounds.** Its author's tour files list nearly every
  event final-first in 2019, 2020 and 2022–2024, and the recipe applies rows in file order
  within a date, so a winner's later-round results reach his earlier rows. This affects the
  CatBoost forecasts on this page in those seasons; its size was not measured.
- **BuildOak's own setup looks ahead on dates.** Its rating-recency reference sits at the
  end of 2025, and the Brisbane and Hong Kong matches dated 2024-12-30 but played in 2025
  are among its training rows for 2025. The fair comparison removes both.

BuildOak does adjust serve and return for the opponent; the difference between the
models is not that.

## Why averaging two models helps

The previous version and the second model are built from different data, training windows
and features, so their mistakes are only partly shared, and averaging cancels part of each
model's errors. The average scores below both members:

| Log loss on every target match | 2017–2024 | 2017–2025 |
|---|---:|---:|
| Matches | 18,972 | 21,561 |
| **Alcaraz (the average)** | **0.5945** | **0.5959** |
| Second model | 0.5947 | 0.5961 |
| Previous version | 0.5976 | 0.5991 |

The gain over the previous version held on seasons never used to build the second model:
−0.0029 [−0.0049, −0.0007] on 2024 (2,679 matches),
−0.0035 [−0.0047, −0.0020] on 2015–2016 (4,806) and
−0.0038 [−0.0053, −0.0024] on 2025 with the bug fixed (2,559).

## Calibration

A descriptive check on 18,888 matches from 2017 to 2024: the slope of a logistic fit
of the outcome on the forecast's log-odds, with no intercept. A slope of one is calibrated;
below one means overconfident. The 70% column is the favourite's side between 65% and 75%.

| Forecast | Slope | Said, 70% bin | Won, 70% bin |
|---|---:|---:|---:|
| Alcaraz | 1.024 | 69.7% | 70.6% |
| Previous version | 1.007 | 69.8% | 70.3% |
| BuildOak, same files and timing rule | 0.909 | 69.9% | 66.9% |
| BuildOak as released | 0.907 | 69.8% | 67.9% |
| tennis-ai CatBoost, main tour | 0.909 | 69.8% | 67.9% |

This was not a registered test; it uses only 2017–2024.
