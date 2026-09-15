# Lane G bounded repair contract

Status: `repair_implementation_only`  
Scope: G1--G7 from the independent executable review  
Reviewed rejected commit: `bf73d1eec95e9586602ea7e2ed33c34228720f3c`  
Review SHA-256: `9a4d26aeadbb3e469cab20157e16e15d334279c6ecf03431f9d4b62bc23640bc`  
Real fit/report status: **not authorized**

## 1. Authority and preservation

This contract is frozen before repair implementation. It supersedes conflicting claims
in `G_LEGACY_DESIGN.md` without changing that rejected design or its config. Preserve:

- original design SHA-256
  `063a1ac0683ee8289a7fe9c7b16493e2ad1400a5f5b83af764016fafff0573b0`;
- original config SHA-256
  `8acb934230137256b9cb58493239381be7c8ba09cd7bd5d1b33053d0209f0829`;
- independent review SHA-256
  `9a4d26aeadbb3e469cab20157e16e15d334279c6ecf03431f9d4b62bc23640bc`;
- all source artifacts, old reports, rejected attempts, and negative-control evidence.

No real forecast, fit, outcome join, price join, score, freeze, merge, push, publication,
traffic, scheduler, account, purchase, or wager is authorized. A later independent review
must bind the repaired commit and transitive code hashes before Lane 0 can create a real
frozen config.

## 2. Stable question and narrowed claim

G-L remains an aligned **rank/Elo diagnostic**, not a broad public-model or state-of-the-
art benchmark. It compares the saved lab incumbent with five transparent comparator
procedures on the frozen market-source-conditioned cohorts:

- ATP TIER01 aligned primary, 2017--2024, n=18,972; priced n=18,882.
- WTA01 aligned primary, 2019--2024, n=12,900; priced n=12,785.

WTA02 is not a substitute. The WTA01 product binding at commit
`87448ab2dce4e65a479adaff01c9650d53eb7820` is independent acceptance evidence, not Lane
G acceptance and not prospective evidence. G-U and public-model breadth remain separate.

The fixed procedures are exactly, in order:

1. `incumbent`;
2. `k32_pooled`;
3. `rank_logistic`;
4. `kovalchik_overall_major`;
5. `fivethirtyeight_surface`; and
6. `welo`.

Ingram is correctly described as a Bayesian point-based aggregate serve/return model. A
future Ingram modern replay needs count-schema/provenance, rights, exact preprocessing,
priors/likelihood, a pinned Stan port, parity controls, chronological refits, and failure
rules. UTS means Ultimate Tennis Statistics and is distinct from proprietary UTR. Neither
is implemented in this bounded repair. FiveThirtyEight's no-major rule remains an explicit
Lane G adaptation; this contract makes no unsupported claim that the article rejected a
major multiplier.

## 3. G1: common calibration is the incumbent equal-year rule

Every reconstructed comparator receives the exact existing
`tennislab.models.pipeline.fit_nonnegative_slope` and `apply_slope` rule:

- three preceding complete calendar years;
- each year has total weight 1/3, and each observation weight
  `1 / (3 * matches_in_year)`;
- probabilities are accepted on `[0,1]`, clipped only for logits to `[1e-6,1-1e-6]`;
- no intercept and slope constrained nonnegative, including the exact zero boundary;
- the incumbent root-bracketing/tolerance and finite-bracket failure conventions;
- incomplete years, invalid arrays, failed fit, or nonfinite result close the attempt.

The unequal-year plant with all p=0.8, year counts `[100,1,1]`, 100 wins in the large
year and one loss in each small year must return slope zero, not 2.821928. All-zero logits
must also return slope zero under the incumbent derivative rule and emit 0.5. Fit receipts
must list the three years, annual counts and membership hashes, union hash, slope, logit
clip count, boundary status, bracket, and failure status, but no prebarrier metric values.

The saved incumbent remains the anchor and is not newly post-hoc calibrated; its two
output aliases are numerically identical.

## 4. G2: probability domains and clipping are separate

Preserve every validated incumbent probability as the same binary float and preserve its
original decimal token in `raw_incumbent` and `calibrated_incumbent`. Do not apply the
logit clip at serialization. A valid source token `0.00000001` must remain that token and
numeric value, not become 1e-6.

- Native imported incumbent domain: finite, strict `(0,1)`.
- Comparator raw domain: finite `[0,1]`; rating/rank methods normally emit strict `(0,1)`.
- Logit/calibration clip: `1e-6`, used only inside the shared calibration math.
- Scoring clip: `1e-15`, used only for natural log loss.
- Brier: `(p-y)^2` on the unmodified probability, with no scoring clip.

Report clipping counts by tour, cohort, raw/calibrated column, and metric. Forecast
receipts report past-calibration logit clip counts without exposing past metric values.

## 5. G3: cutoff-gated sports projection and truthful access receipts

The forecast process may open the configured prepared panel even when the price role is an
alias of that file; it must report that fact. It must select only a declared sports-column
projection and never access price columns numerically. Use a column-index reader rather
than materializing every CSV field into dictionaries.

Split panel handling into two passes:

1. metadata projection for all candidate rows, selecting only match ID, match date,
   neutral pair, surface, level, tournament anchor and named date/anchor bases; and
2. outcome/score projection only for exact rows admitted by a declared history, rank-fit,
   or calibration membership and only after its date/year cutoff is known.

Do not parse `a_won`, status, played, retirement, walkover, or score for a row that is
unavailable to every forecast/fit in the attempt. A final target whose outcome token is
`UNAVAILABLE_AFTER_FINAL_CUTOFF` must still forecast successfully. A row may be eligible
for a later target while unavailable to an earlier target; rating state uses per-target
D-2 cutoffs and pre-update date batches. Rank and calibration labels stop at the exact
prior-year membership.

The access receipt is derived from actual selected columns and admitted row keys. It
records opened paths, selected column names, max parsed outcome date, parsed outcome count
and membership hash, excluded column categories, and per-tour/per-purpose membership. It
must not claim that an aliased price-bearing path was never opened.

## 6. G4/G5: completed-stage and content commitment

### Forecast completion

The successful forecast tree contains exactly this allowlist:

- `predictions.csv`;
- `fit_receipts.json`;
- `fallback_counts.csv`;
- `access_receipt.json`;
- `source_manifest.json`; and
- `stage_manifest.json`.

No root or forecast failure receipt may exist. `stage_manifest.json` has a strict schema:
unknown/missing keys or wrong types fail. It binds invocation/effective config hashes,
repair contract/review/base config hashes, exact source bindings, effective procedure
list/constants, dependency versions, transitive effective-code receipts, row/membership
hashes, and every other allowlisted forecast artifact hash. The artifact map excludes only
the manifest itself by declared schema; arbitrary content in that file is never blindly
skipped.

### Barrier

Before commitment the barrier verifies the successful stage manifest against current
bytes, current config, current source bytes, constants/procedure contract, dependencies,
and currently executing transitive code. It rejects missing/extra artifacts, absent or
failed stage manifests, any failure receipt, and mutations even when a caller edits only
the config or prediction while leaving the old manifest intact. An authorized alteration
requires a new attempt.

The content scanner has one declared reader for case-insensitive `.csv`, `.csv.gz`,
`.json`, and `.jsonl`. It applies both metric and outcome/price-sensitive checks.
Unsupported formats reject. Ordinary JSON, gzip CSV, and a planted sensitive field in the
stage manifest must all reject. The barrier commitment binds the verified forecast
manifest hash, current code/dependencies/config/sources, exact artifact bytes and scan
receipt.

### Report

Report verifies the barrier and current config, source bindings, dependencies, and all
transitive forecast/scoring code before opening report-only outcome/price fields. Code
mutation after the barrier rejects even if it is comment-only. The report stage is
single-use and writes a strict completion manifest; failures remain immutable.

For a future real freeze, `reviewed_runtime` in the config must contain the independently
reviewed commit, module hashes and dependency versions. `PENDING_INDEPENDENT_REVIEW`
cannot run real forecast/report.

## 7. G6: executable configuration and reconciled inputs

The implementation validates rather than silently ignores fixed constants. The config
must exactly match these values:

- initial Elo 1500; scale 400; K32 32;
- decaying K numerator 250, offset 5, exponent 0.4;
- Kovalchik major multiplier 1.1;
- FiveThirtyEight weights 0.71 overall and 0.29 surface;
- calibration years 3; rank parameter history 5;
- logit clip 1e-6; scoring clip 1e-15; and
- the exact procedure list above.

Any drift rejects. Required tour/year/major/price/anchor schemas and numeric inference
controls validate before output creation. Feature/panel joins reconcile exact canonical
pair, match date, surface and level for every used key. Missing tournament anchor rejects;
the named cluster basis is `tourney_anchor_date_event_anchor_proxy`, not an asserted match
date or publication time. Dates remain retrospective proxies under the legacy contract.

Synthetic rehearsal is technically confined:

- inputs are under a non-symlink `fixtures/synthetic/<fixture_id>/` subtree;
- a hash-bound `fixture_manifest.json` lists every input byte and row count;
- every match ID starts with `SYNTHETIC-`, every source file is at most 1,000 data rows,
  and only ATP/WTA fixture tours are accepted;
- real archive paths/hashes and proposal statuses cannot be relabeled synthetic.

Fallback receipts are rows at `(tour, calendar_year, service, scope, reason)` grain,
including zero rows for every declared service/year/reason. Rank missingness, unknown
surface overall-only behavior, fresh-player initialization and WElo unparsed-game updates
are explicit. Fit/calibration receipts bind exact years and membership hashes.

## 8. G7: complete paired reporting

Build one asserted paired membership per tour/cohort. Missing procedure predictions,
duplicates or key differences reject. For every raw and calibrated procedure emit:

- annual n, natural log loss and binary Brier;
- equal-year mean log loss and Brier;
- match-weighted mean log loss and Brier;
- annual, equal-year and match-weighted incumbent-minus-comparator contrasts; and
- native coverage, fallback counts/reasons, and log-loss clipping counts.

The primary calibrated-log-loss max-|t| family remains the five incumbent-minus-comparator
contrasts, separately by tour. Do not add Brier inference. Retain L=4/8/13 stationary
bootstrap outputs.

On the exact priced keys, after the barrier, add:

- normalized Pinnacle `q_A / (q_A + q_B)`, where `q=1/decimal_odds`; and
- past-only equal-year-calibrated normalized Pinnacle using the same three-prior-year
  slope rule and only valid priced primary rows.

Both market references use the identical priced target keys as every sports procedure and
carry unknown-quote-time/later-information qualifications. Report their calibration years,
memberships and logit clipping. They do not enter the five-method max-|t| family.

### Fixed-prediction year sensitivities

For every calibrated-log-loss primary contrast, emit leave-one-year-out point estimates
for each year and a separately labeled leave-2020-out estimate when 2020 is present. These
reuse already fixed predictions: there is no refitting and no independent-fold claim.

### Bootstrap stream and limits

The seed formula is exactly:

`seed = 20260914 + tour_offset + L`, where ATP offset=1000 and WTA offset=2000.

The generator is reset separately for each `(tour, cohort, L)`; primary and priced are
distinct streams that intentionally begin from the same derived seed. Use NumPy PCG64.
Validate before calculation: replicates >=2, maximum draws >= replicates, L>0,
`0<confidence_level<1`, and finite nonnegative degeneracy tolerance.

The stationary bootstrap remains conditional on fixed saved forecasts and the declared
week dependence model. It does not include fit/selection/source-choice uncertainty. The
proposed unordered-player-dyad/player-cluster sensitivity is **deferred from this bounded
repair** because no accepted dyadic estimator/degeneracy contract is defined. Its absence
and the conditional-bootstrap limits must appear in the report before any result; it may
not be silently implied complete.

## 9. Public negative controls and acceptance

Public tests must reproduce every independent counterexample before repair and pass after:

- G1 unequal-year slope and all-zero-logit slope;
- G2 extreme incumbent token/value preservation;
- G3 final unavailable outcome plus actual-read receipt;
- G4 config/prediction mutation before barrier, empty/failed stage, code mutation after
  barrier and malformed/absent completion;
- G5 ordinary JSON, gzip CSV and manifest sensitive-field plants;
- G6 inert constants/procedure drift, arbitrary synthetic relabeling, cross-artifact
  key/date/pair/surface/level mismatch, missing anchor, fit/fallback receipt grains;
- G7 paired raw/calibrated LL/Brier annual/equal-year/match-weighted output, normalized and
  past-calibrated market references, year-exclusion sensitivities, malformed statistics
  controls, exact seed/stream receipts, and no Brier inference family.

Also retain the original successful controls: rating arithmetic, same-day shuffle, swap,
future-value and price-value invariance, duplicates, failure retention, output containment,
postbarrier byte/config rejection and CLI forwarding.

Passing tests establishes repair conformance only. Independent reconstruction at the new
commit remains required; no performance or scientific acceptance follows.
