# Methods and evidence boundary

This page explains what the retained model results measure and what the current software
checks establish. It does not turn retrospective output into prospective evidence.

## Populations and actual horizons

The two accepted retrospective configurations have different histories and target years.
The repository date is not a shared data through-date.

| Tour | Configured panel | Feature-history floor | Target years | All targets | Identical priced cohort |
|---|---|---|---|---:|---:|
| ATP | 2005–2024 | 2011 | 2017–2024 | 18,972 | 18,882 |
| WTA | 2007–2026 | 2011; serve counts from 2016 | 2025–2026 | 4,296 | 2,344 |

The configuration locators are `configs/chains/atp_tier01_2017_2024.json` and
`configs/chains/wta02_2025_2026.json`. All-target counts come from each accepted run's
`report/primary.json`; priced counts come from generated `docs/ladder.json`.

ATP covers tour-level men's singles plus the lower-tier history used by `full_tier`.
WTA applies the same product trunk with tour-specific source and feature rules. The WTA
2025–2026 target window is spent development evidence: retained 2026 bridge rows exposed
chronology defects, and that window is not a holdout.

The sports feature bundles contain no price predictor. However, the historical panel and
evaluation population are market-source-aligned: WTA panel construction iterates matched
market rows, while ATP preparation starts from market/common-panel candidates. Therefore
the results support these source-covered cohorts, not all public tennis results. A broader
public-results population remains a future benchmark prerequisite.

Every result has two distinct estimands:

- **all targets**, for sports-model versus sports-model comparisons; and
- **identical priced targets**, for comparisons that include the market reference.

Player orientation is neutral: the first player is assigned by a stable identity order,
the target is whether that player won, and the feature definitions are symmetric.

## Cutoff and date semantics

The historical configurations use an inclusive D−2 rule: a history row must be eligible
at least two calendar days before the target's date basis. That basis is material.

- A reported calendar match date is day-level evidence, not a publication timestamp.
- An event anchor identifies a tournament; it does not show when a later result became
  available.
- An event-completion bound is conservative only within its demonstrated source contract.
- Charter-asserted dates and later receipt dates remain separate fields.

The archive learned this distinction through failures. Round-order arithmetic dated a
2026 Canada final four days early; its result changed two later Cincinnati feature rows.
Overlapping Toronto and Cincinnati events remained unordered even under event-end dating.
Four-leg satellite circuits were released after one week although some ran for four.
The corrected ATP tier run dates each satellite circuit at its last possible completion
and re-estimates learned debut offsets before the training window that consumes them.

The current product has regression and mutation checks for parts of this contract, but it
does not prove every historical row's real-world availability. The live workflow's
rejections and scoped synthetic acceptance are documented in the process page.

## Model ladder

Each rung adds a declared statistics block to the same chronology and evaluation path.

1. **Elo** averages the overall- and surface-Elo win probabilities; K = 32, scale = 400,
   with no fitted calibration in the displayed rung.
2. **base** uses a HistGradientBoosting classifier over results-derived Elo, rankings,
   workload, match context, and available serve/return counts.
3. **full** adds player traits and SR02 dynamic serve/return states replayed match by match.
4. **full_tier** (ATP only) adds qualifying, Challenger, and Futures history, including a
   tier-aware Elo, experience counts, and tier serve/return states.

These names map to `atp_p0`, `atp_p1`, `atp_full_tier`, `wta_base`, and `wta_full` in
`configs/`. The WTA product has no tier rung; a shared label does not imply that support.

## Walk-forward fitting, selection, and calibration

For each target year, candidate models train within the configured five-year past window.
Selection and a nonnegative, intercept-free calibration slope use the three prediction
years immediately before the target. Learned constants carry a receipt naming the data
horizon that produced them. A constant's horizon must precede the first row it touches.

The retained archive did not always enforce the intended outcome barrier. Its SR03 stage
wrote development-year scores before the final report stage, and an earlier confirmation
attempt wrote reserved-year scores before that barrier. The current B2 trunk repairs this
engineering contract:

- fold-specific accessors bound training outcomes to the consuming fold;
- runtime access logs compare declared and observed file reads;
- SR03 emits forecasts before the barrier and its component scores after it;
- selection criteria are committed before the barrier and recomputed after it; and
- supported pre-barrier artifacts are scanned for metric-shaped content before freezing.

Independent reconstruction verified unchanged forecasts and final reports after this
repair. The implementation instruments file access; it is not a security sandbox or an
independent holdout custodian.

## Integrity checks: admitted scope

The current product includes controls demonstrated against planted failures, not a claim
that every possible leak has been excluded.

- Native future-outcome invariance covers the actual ATP tier path and WTA base path,
  including exact target membership and omission/duplicate controls.
- T2 covers its repaired dtype, name, and metadata date-discovery scope.
- T9 checks learned-constant horizons, T10 re-hashes manifest leaves, and ATP T11/T13
  check the declared estimand and univariate target proxies within their fixtures.
- The runtime barrier rejects declared planted metric artifacts and undeclared reads.

Open scope includes WTA tier support, full-bundle T3 label shuffling, full fit-frame and
identity/swap coverage, chronology channels outside the tested adapters, and several C2
detectors that remain diagnostic. `docs/INTEGRITY.md`, `docs/NATIVE_T1.md`, and
`docs/B2_REVIEW.md` give the exact acceptance boundary.

## Market reference and comparison limits

The market reference is Pinnacle's annual closing-like price from tennis-data.co.uk
workbooks, shown normalised for overround and, separately, calibrated with a past-fit
logistic slope. The workbooks do not provide a verified quote time, while match dates
are usually day-level. The comparison is therefore descriptive, not equal-cutoff.

On the identical priced cohorts, match-weighted log loss is:

| Tour | Best sports rung | Normalised Pinnacle | Paired gap, sports minus market |
|---|---:|---:|---:|
| ATP, 18,882 matches | 0.5984 | 0.5873 | +0.0112 [0.0090, 0.0134] |
| WTA, 2,344 matches | 0.6153 | 0.5953 | +0.0200 [0.0127, 0.0279] |

Source: generated `docs/RESULTS.md`, match-weighted paired contrasts. A positive gap means
the sports model had higher loss. It does not establish why, and it neither proves nor
disproves a claim relative to other public statistics-only models. No accepted external
public-model benchmark has been run on these cohorts.

## Scores and uncertainty

The primary proper score is log loss; Brier score is also retained. Reports show both
match-weighted and equal-year means, never as interchangeable summaries. Contrasts are
paired on identical matches.

Winner-picking accuracy is a descriptive companion metric. A probability above 0.5 picks
player A, one below 0.5 picks player B, and exactly 0.5 is a tie. Generated accuracy is
`(correct + 0.5 × ties) / n`, so every model retains the full identical priced cohort and
ties remain visible rather than being assigned arbitrarily. Accuracy was not a fitting or
selection target and has no new uncertainty claim. `tools/render_winner_accuracy.py`
reads the accepted saved forecasts and labels, refuses a year whose matched count differs
from `docs/ladder.json`, and writes aggregate-only `docs/winner_accuracy.csv` and
`docs/winner_accuracy.json`.

The displayed 95% intervals use 2,000 match-level bootstrap replicates stratified by year
with seed 20260912. They are conditional on the saved forecasts and do not propagate
fitting, selection, or calibration uncertainty. Per-year results share players, data,
and model ancestry; they are robustness checks, not independent replications. Public
documentation rounds to four decimals.

On all targets, the registered equal-year delta for ATP `full_tier − full` is −0.0068
(n = 18,972), and WTA `full − base` is −0.0044 (n = 4,296). Those are internal rung
comparisons on exposed data, not market or prospective claims. Exact values and receipts
are in `data/registries/leaderboard.csv` and the accepted run reports.

## Negative and inconclusive work stays visible

The archive retains the alternatives that did not earn promotion:

- MULTI02's selected market-plus-sports model moved −0.0003 in match-weighted log loss
  versus its calibrated-price baseline on 18,903 matches, but its registered equal-season
  interval crossed zero.
- MULTI03's selected full model equalled calibrated Pinnacle to the displayed precision
  on the same 18,903-match cohort.
- JOINT05 moved +0.0001 versus its calibrated-market baseline on 18,882 matches; the
  registered equal-year contrast was also positive.
- The TEACHER04 policy failed its scientific gates and promoted no model.
- WX11's weather block worsened match-weighted log loss by +0.0263 on 1,687 matches.
- FAT01's fatigue block moved +0.0001 match-weighted on 18,972 matches; its registered
  equal-year interval spanned zero.

The exact metric fields, cohorts, evidence status, and artifact hashes are in
`data/registries/leaderboard.csv`. These results retire the tested specifications, not
their broader ideas.

## Prospective status

Nothing here is prospective confirmation. The 2025–2026 window was opened, repaired,
and reviewed; it is development data. No real batch has been issued before play and later
scored under a frozen stopping rule. The manual workflow has passed scoped independent
synthetic reconstruction; qualified real-source binding, the D2 snapshot, and integrated
CI remain separate prerequisites before real issuance can create such evidence.
