# The frozen model applied to 2025 (REFIT2025)

> **Independently reconstructed (archive decision D137).** The frozen recipe (D134) was run
> once more with 2025 as the target season, on the same pinned inputs extended by one year.
> Nothing was redesigned or tuned. Registration and freeze preceded the run
> (`references/REFIT2025/FREEZE_2026-09-24.json` in the research archive); every 2017–2024
> forecast reproduced byte for byte; one scoring pass; separate reconstruction.

## What this is and is not

Alcaraz is a recipe run once per season: train on the five seasons before the target,
select and calibrate on the three most recent of those, forecast each target match at its
two-day cutoff. This page is the ninth run of that recipe, with 2025 as the target. The
model never trained on a 2025 result. It is **not a prospective test and not a clean
holdout**: every 2025 match had been played, and the 2025 window had been opened and read
by earlier work before the recipe was frozen (the archive's exposure log records each
read). It answers a narrower question: applied unchanged to a season it never saw in
training, does the model hold its ground?

## Registered outcome

On the 2,479 priced ATP matches of 2025, log loss was **0.6136** for the frozen
model, **0.6025** for Pinnacle and **0.6339** for the Elo-only rung. Model minus
Pinnacle **+0.0111 [+0.0048, +0.0174]**; model minus Elo -0.0203
[-0.0289, -0.0115]. The pre-registered cliff check (model minus Elo within the
2017–2024 range of −0.036 to −0.020) passed. Correct picks: 65.6% (model),
67.1% (Pinnacle), 62.9% (Elo).

| Season | Priced matches | Elo only | Alcaraz | Pinnacle | Alcaraz − Pinnacle [95%] | Alcaraz − Elo |
|---|---:|---:|---:|---:|---:|---:|
| 2017 | 2,311 | 0.6124 | 0.5917 | 0.5875 | +0.0042 [-0.0024, +0.0107] | -0.0207 |
| 2018 | 2,587 | 0.6345 | 0.6029 | 0.5916 | +0.0113 [+0.0058, +0.0169] | -0.0316 |
| 2019 | 2,491 | 0.6279 | 0.6061 | 0.5944 | +0.0117 [+0.0059, +0.0173] | -0.0218 |
| 2020 | 1,241 | 0.6191 | 0.5937 | 0.5747 | +0.0190 [+0.0098, +0.0285] | -0.0254 |
| 2021 | 2,384 | 0.6273 | 0.5962 | 0.5905 | +0.0057 [-0.0006, +0.0120] | -0.0311 |
| 2022 | 2,525 | 0.6162 | 0.5928 | 0.5824 | +0.0104 [+0.0040, +0.0167] | -0.0233 |
| 2023 | 2,672 | 0.6267 | 0.5973 | 0.5874 | +0.0099 [+0.0043, +0.0155] | -0.0294 |
| 2024 | 2,671 | 0.6220 | 0.5959 | 0.5836 | +0.0123 [+0.0066, +0.0179] | -0.0261 |
| 2025 | 2,479 | 0.6339 | 0.6136 | 0.6025 | +0.0111 [+0.0048, +0.0174] | -0.0203 |

2017–2024 are the frozen ladder's rows, rescored from this run's byte-identical files.
2025 is a harder season for everyone: Pinnacle itself scores 0.019 worse than in 2024.
The gap to the market in 2025 sits inside the eight-year range. The margin over the Elo
rung (−0.0203) is the smallest of the nine seasons: it passes the registered cliff range
(−0.036 to −0.020) but falls 0.0004 outside the exact 2017–2024 per-year range
(−0.0316 to −0.0207), which the registration had mis-stated on the wide side. The archive
decision records both readings; the interval excludes zero and the market gap is
mid-range, so the conclusion is "no cliff, Elo margin at the low end of its history".

## Wimbledon 2025, men's main draw

Green Code's second video reports 66.3% correct picks for his model on this draw, with the
bookmakers at 72% and IBM at 63.8% (by his account; no match list or probabilities are
published). The frozen model, issued two days before each match, picked
**71.7%** of winners on all 127 main-draw matches [63.8, 79.5], log loss 0.5987.
On the 120 matches with a Pinnacle price, the model picked 70.0% and Pinnacle 70.8%
(log loss 0.6300 against 0.6117). Pinnacle's figure being close to his
"72%" suggests the match sets are comparable; the interval on 127 matches is about ±8
points, so the comparison is a same-tournament reading, not a ranking.

## What had to change to run 2025, and what did not

- The 2025 lower-tier files, rankings and players were already in the pinned mirror.
- Two product changes, both with byte-identity proofs for 2024 and earlier: the lower-tier
  stage now opens a spent reserved year only with explicit acknowledgement, and it maps a
  2025 source drift (1,175 Futures rows with lowercase surfaces) to the canonical spelling.
- The market join fell to 88% because the player-alias and event pins stopped at 2024; 297
  player and 60 event pins for 2025 were curated by identity evidence only (names, initials,
  nationality, birth date, rank, event, week, opponent) and restored it to 99.1%.
- Nothing in the model changed. Every 2017–2024 forecast is byte-identical to the frozen
  files (202 of 202 and 92 of 92 files).

## The women's tour, same procedure (secondary)

The frozen women's rung (`full_entry`) was run once with 2025 as the target, on the same
mirror extended by one year; every 2019–2024 forecast reproduced byte for byte (156 of 156
files). On the 2,243 priced WTA matches of 2025, log loss was 0.6160 (model),
0.5965 (Pinnacle) and 0.6277 (Elo); model minus Pinnacle
+0.0195 [+0.0120, +0.0272], inside the 2019–2024 range. The Wimbledon 2025
women's draw: 67.7% correct [59.1, 75.6] on 127 matches; on the 126 priced rows the
model's log loss (0.5924) is below Pinnacle's (0.6064), with picks at 68.3% against
67.5%.

| Season | Priced matches | Elo only | Alcaraz | Pinnacle | Alcaraz − Pinnacle [95%] | Alcaraz − Elo |
|---|---:|---:|---:|---:|---:|---:|
| 2019 | 2,317 | 0.6341 | 0.6178 | 0.6002 | +0.0177 [+0.0107, +0.0246] | -0.0163 |
| 2020 | 1,013 | 0.6281 | 0.6145 | 0.6039 | +0.0106 [-0.0022, +0.0235] | -0.0136 |
| 2021 | 2,321 | 0.6165 | 0.6008 | 0.5756 | +0.0252 [+0.0178, +0.0328] | -0.0157 |
| 2022 | 2,307 | 0.6301 | 0.6113 | 0.5915 | +0.0198 [+0.0125, +0.0270] | -0.0188 |
| 2023 | 2,439 | 0.6224 | 0.6122 | 0.5903 | +0.0219 [+0.0148, +0.0291] | -0.0102 |
| 2024 | 2,388 | 0.6253 | 0.6043 | 0.5884 | +0.0159 [+0.0083, +0.0235] | -0.0210 |
| 2025 | 2,243 | 0.6277 | 0.6160 | 0.5965 | +0.0195 [+0.0120, +0.0272] | -0.0117 |

The 2025 market join is 96.4% (2024: 99.8%): three events new in 2025 (Singapore, São
Paulo, Queen's) have no earlier edition to map from and were not curated. This secondary is
descriptive, as registered. The archive record lists its procedural exceptions: the run
had no separate lead freeze (the executing agent's pre-run bindings cover every input it
read), and the record, the scorer's tour argument and the scoring pass were written in one
sequence. Machine-readable aggregates: [refit2025_wta.json](refit2025_wta.json).

## Limits

- Exposed retrospective work: the season had been inspected before the freeze.
- Pinnacle is missing on part of October 2025 (Paris, Basel, Vienna) in the source.
- Three Roland Garros rows recorded as best-of-three by the source received no forecast,
  by the recipe's rule that nothing is guessed.
- Twenty-eight season-2025 matches played on 29–31 December 2024 fall between the recipe's
  yearly folds and have no forecast, as 49 such matches do across 2017–2025.
- The reconstruction rejected the first result on procedure (a presentation-only edit to
  the scorer after the pass, unrecorded at the time); the correction is recorded in the
  archive's freeze file and every number reproduces.

Machine-readable aggregates: [refit2025.json](refit2025.json).
