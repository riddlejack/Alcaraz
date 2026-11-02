# Methods and evidence boundary

This page explains what the retained model results measure and what the current software
checks establish. It does not turn retrospective output into prospective evidence.

The current version of Alcaraz averages the previous version with a second, all-tier model
(ATP only), described [below](#the-second-model-and-the-average). Unless a row or section
names the current version, this page describes the previous version's pipeline, which the
current version keeps unchanged as one of its two members. The current version's comparisons are on
[CURRENT_2017_2025_RESULTS.md](benchmarks/CURRENT_2017_2025_RESULTS.md).

## Populations and actual horizons

The two accepted retrospective configurations have different histories and target years.
The repository date is not a shared data through-date.

| Tour | Configured panel | Feature-history floor | Target years | All targets | Identical priced cohort |
|---|---|---|---|---:|---:|
| ATP | 2005–2025 | 2011 | 2017–2025 | 21,561 | 21,361 |
| WTA (WTA01) | 2007–2025 | 2011; serve counts from 2016 | 2019–2025 | 15,251 | 15,028 |
| WTA (WTA02) | 2007–2026 | 2011; serve counts from 2016 | 2025–2026 | 4,296 | 2,344 |

The configuration locators are `configs/chains/atp_tier01_2017_2024.json` and
`configs/chains/wta01_2019_2024.json` for the accepted seasons, the archive's REFIT2025
chains for 2025 (the frozen model run once on 2025), and `configs/chains/wta02_2025_2026.json`.
The 2017–2025 and 2019–2025 all-target counts come from
`docs/benchmarks/buildoak_2017_2025.json` and `docs/benchmarks/buildoak_wta_2019_2025.json`,
the WTA02 count from its accepted run's `report/primary.json`; priced counts come from
generated `docs/ladder.json`. 2025 was inspected before the model was frozen: every 2025
number is exposed retrospective data, not a holdout.

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
rejections and scoped synthetic acceptance are documented in [live.md](live.md).

## Model ladder

Each rung adds a declared statistics block to the same chronology and evaluation path.

1. **Elo** averages the overall- and surface-Elo win probabilities; K = 32, scale = 400,
   with no fitted calibration in the displayed rung.
2. **base** uses a HistGradientBoosting classifier over results-derived Elo, rankings,
   workload, match context, and available serve/return counts.
3. **full** adds player traits and SR02 dynamic serve/return states replayed match by match.
4. **full_tier** (ATP only) adds qualifying, Challenger, and Futures history, including a
   tier-aware Elo, experience counts, and tier serve/return states.
5. **full_tier_entry** (ATP) and **full_entry** (WTA) add nine declared columns: the signed
   differences of the Q, LL, WC and PR entry codes, a symmetric any-qualifier flag, and
   one-hot tournament-level flags. These are the frozen models (archive decision D134).

These names map to `atp_p0`, `atp_p1`, `atp_full_tier`, `atp_full_tier_entry`, `wta_base`,
`wta_full`, and `wta_full_entry` in `configs/`. The WTA product has no tier rung; a shared
label does not imply that support. `full_tier_entry` is the previous version.

The current version adds one more step on the men's tour: it averages `full_tier_entry` with
the second model in log-odds, `σ(½·logit(p_previous) + ½·logit(p_second))`, with the
weights fixed before any test.

## The second model and the average

The second model (ATP only) is a gradient-boosted classifier on a separate, all-tier
point-in-time table. It shares no fitted state with the previous version.

**Rows and dates.** One row per Sackmann match of every tier from 1991: tour, qualifying,
Challenger and Futures; team events are excluded, and walkovers stay as rows without
updating any outcome-based state. Lower-tier rows carry the tier stream's conservative
release date (the Monday after the event's week); tour rows from 2005 carry the panel's
match date; earlier tour rows carry the tournament date plus a round offset estimated from
the 2005 onward panel, a small residual timing risk confined to pre-2005 rows.

**Release rule.** The builder walks the distinct dates in order. Before it computes the
features of the rows dated d, it releases every row dated two or more days earlier, and
only a release changes any rating or history. Nothing is normalised or fitted over the
table, so no feature depends on a later row. Planted controls pass: rewriting a row's own
outcome, rewriting or deleting every later row, and swapping the two players leave the
checked features unchanged (or exactly negated, for the swap).

**Features.** All-tier, tour-only and surface Elo, with tier-weighted updates; a rating
deviation that widens while a player is idle; serve- and return-points-won rates with
exponential decay; an opponent-adjusted point model (server skill minus returner skill)
turned into a match-win probability through exact game, tiebreak and set chains; form over
recent matches and games; activity windows and rest; career experience by tier; ranking,
ranking points and their momentum; age, height and handedness; head-to-head; and match
context. Signed features are differences between the two players and negate under a swap.

**Kalman serve/return block.** Each player's serve and return strength is a logit-scale
estimate with its own variance, plus a small per-surface deviation. Every released match
with serve counts updates both serving sides by one extended Kalman (Newton) step on the
binomial count of serve points won; variances grow with idle days up to a cap. Its four
settings (prior variance, daily process noise, surface variance and a lower-tier temper)
were chosen on the binomial log-likelihood of 2000–2010 serve points, from a grid whose
every setting is recorded; no season after 2010 was read.

**Training and calibration.** Tour, qualifying and Challenger matches that were completed
or retired are training examples. For each target season the model is fitted on three
windows, the last 8, 12 and 16 seasons; each window chooses among three tree settings and
fits a nonnegative, intercept-free calibration slope using only the three seasons before
the target. The second model is the mean of the three windows' log-odds.

**Selection labels.** The 2025 pass first ran with 2024's results blanked in the file the
selection step read, so the 2025 settings were chosen on invalid labels; the corrected pass
restored them. Every forecast generator now asserts a valid label on every selection row
before it selects.

**The average.** For every match the current version is
`σ(½·logit(p_previous) + ½·logit(p_second))`. The equal weights were fixed in advance and
never fitted on test data. The two members are built from different data, windows and
features, so their errors are only partly shared and the average scores below both
(see [CURRENT_2017_2025_RESULTS.md](benchmarks/CURRENT_2017_2025_RESULTS.md#why-averaging-two-models-helps)).

**Comparisons.** Each rival comparison pairs the two forecasts on the matches both cover
and resamples whole calendar weeks (stationary bootstrap, mean block eight weeks), with
four- and thirteen-week blocks as checks and Holm adjustment across a pass's primary
contrasts. "BuildOak on the same files and timing rule" means BuildOak given the same
lower-tier files, the same two-day release, a rating-recency reference at each season's
boundary and nationality buckets from fit rows only.

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
detectors that remain diagnostic.

## Market reference and comparison limits

The market reference is Pinnacle's annual closing-like price from tennis-data.co.uk
workbooks, shown normalised for overround and, separately, calibrated with a past-fit
logistic slope. The workbooks do not provide a verified quote time, while match dates
are usually day-level. The comparison is therefore descriptive, not equal-cutoff.

On the identical priced cohorts, match-weighted log loss is:

| Tour | Best sports rung | Normalised Pinnacle | Paired gap, sports minus market |
|---|---:|---:|---:|
| ATP 2017–2025, 21,361 matches, current version | 0.5961 | 0.5890 | +0.0071 [0.0053, 0.0089] |
| ATP 2017–2025, 21,361 matches, `full_tier_entry` | 0.5993 | 0.5890 | +0.0102 [0.0082, 0.0123] |
| WTA 2019–2025, 15,028 matches, `wta_full_entry` | 0.6106 | 0.5913 | +0.0194 [0.0165, 0.0223] |
| WTA 2025–2026, 2,344 matches, `wta_full` | 0.6153 | 0.5953 | +0.0200 [0.0127, 0.0279] |

Source: [RESULTS.md](RESULTS.md), match-weighted paired contrasts. A positive gap means
the sports model had higher loss. It does not establish why, and it neither proves nor
disproves a claim relative to other public statistics-only models. Matched comparisons
with public models are reported separately in `docs/benchmarks/`; they use their own
cohorts and are never read off this table.

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

Nothing here is prospective confirmation, and the current version has issued no forecast
before play. The 2025–2026 window was opened, repaired,
and reviewed, and 2025 was scored again for the frozen model and its extended comparisons;
it is development data. No real batch has been issued before play and later
scored under a frozen stopping rule. The manual workflow has passed scoped independent
synthetic reconstruction; qualified real-source binding, the D2 snapshot, and integrated
CI remain separate prerequisites before real issuance can create such evidence.
