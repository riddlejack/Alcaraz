# Methods

Status: skeleton; every section is filled from the archive's designs
(`experiments/TIER01.design.md`, `experiments/WTA02.design.md`, `experiments/MULTI01.design.md`,
`experiments/SR02-C1.json`, `experiments/SR03.design.md`) at integration and checked
against the generated results.

## Population

- **ATP:** annual singles 2005–2024 from the pinned Sackmann mirror (levels A/M/G, Olympics,
  main Tour Finals; team events and NextGen excluded), 51,222 panel rows; targets are the
  aligned primary-identity matches of 2017–2024 (18,972), of which 18,882 carry a Pinnacle
  closing-like price.
- **WTA:** tour-level singles 2007–2026 under the same rule with the WTA level vocabulary;
  targets 2025–2026 (4,296 aligned primary; 2,344 priced).
- Neutral player orientation (`a_entity_id < b_entity_id`); labels are `a_won`.

## Cutoffs and information set

- Reported match date minus two calendar days (D−2) for every history feature and
  ranking lookup. Event-anchored rows are bounds, never clocks (`chronology/dating.py`).
- Satellite circuits are dated at anchor + 7 days per leg; draw-page rows at the event end.
- Learned constants (TIER offsets, calibration slopes, selected candidates) carry receipts
  naming the data horizon, which precedes every row they are applied to.

## Models

One trunk, configurations per rung: pooled Elo; P0 (base HGB on match-history
features); P1 (full: traits and SR02 dynamic serve/return states); full_tier (P1 plus
qualifying/Challenger/Futures history and the tier-inclusive Elo). Past-only candidate
selection and calibration inside chronological training boundaries (five-year window,
three calibration years).

## Scoring

Log loss and Brier, match-weighted and equal-year; paired deltas on identical
populations; one declared interval type per table; four-decimal rounding. Market
comparisons are descriptive: annual Pinnacle prices are closing-like with unknown quote
times.
