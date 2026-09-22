# BuildOak fairness audit — September 2026

The finite audit is complete and independently accepted. Local repository checks pass: 647 tests, three skips, Ruff/formatting, and both synthetic reproductions.

The accepted full-system ATP and WTA 2024 comparisons reproduce unchanged. Alcaraz has slightly lower proper-score point estimates on both tours, but the paired intervals include zero. BuildOak makes 14 more correct WTA picks; Alcaraz makes three more correct ATP picks. These are exposed retrospective comparisons of complete systems with different legitimate histories, not an untouched test or evidence of universal superiority.

| Full-system population | Model | Log loss | Brier | Correct picks | Accuracy |
|---|---|---:|---:|---:|---:|
| ATP 2024, 2,681 matches | Alcaraz full-tier | 0.596486 | 0.206223 | 1,774 | 66.1693% |
| ATP 2024, 2,681 matches | BuildOak adaptation | 0.600044 | 0.207701 | 1,771 | 66.0574% |
| WTA 2024, 2,404 matches | Alcaraz full | 0.604022 | 0.209406 | 1,575 | 65.5158% |
| WTA 2024, 2,404 matches | BuildOak adaptation | 0.605039 | 0.209741 | 1,589 | 66.0982% |

All targets receive a native external prediction. The qualified target cohorts cover 2,681 of 3,076 raw ATP 2024 rows and 2,404 of 2,689 raw WTA 2024 rows; the raw files and qualified scoring populations are different denominators. Source winner/loser identities agree on every qualified target. ATP predictors disagree on 305 winners (Alcaraz correct 154, external 151); WTA disagrees on 246 (116 versus 130).

Differences below are Alcaraz minus BuildOak. Lower loss/Brier and higher accuracy favor Alcaraz. Intervals use the original paired stationary calendar-week bootstrap: 5,000 draws, mean block length 8, including empty calendar weeks. Lengths 4/13 are prespecified sensitivities and also cross zero. ATP Brier and accuracy intervals are supplemental audit endpoints under the unchanged draw plan. These intervals condition on fixed forecasts and omit refit, source-choice and accumulated research uncertainty.

| Full-system population | Log-loss difference, 95% interval | Brier difference, 95% interval | Accuracy difference, percentage points, 95% interval |
|---|---:|---:|---:|
| ATP 2024 | −0.003558 [−0.011207, +0.003013] | −0.001478 [−0.004443, +0.001035] | +0.1119 [−0.9371, +1.1198] |
| WTA 2024 | −0.001017 [−0.005715, +0.003742] | −0.000335 [−0.002418, +0.001748] | −0.5824 [−1.9326, +0.6857] |

The registered completed-only sensitivities retain 2,604 ATP and 2,327 WTA matches. ATP log losses are 0.592442 versus 0.597154; WTA 0.600285 versus 0.600161. The small WTA direction reverses. Retirements remain in the primary populations; this sensitivity does not replace them.

## Secondary: controlled shared-data WTA comparison

On the frozen common-input contract, **Alcaraz has lower log loss and Brier and makes 39 more correct picks** than the BuildOak adaptation. This is a supported, scoped pipeline advantage. It does not replace the primary full-system result, where BuildOak retains its legitimate data and history and the paired difference remains inconclusive.

| WTA 2024 shared-data control, 2,404 matches | Log loss | Brier | Correct picks | Accuracy |
|---|---:|---:|---:|---:|
| Alcaraz, exactly reused inputs and forecasts | 0.604022 | 0.209406 | 1,575 | 65.5158% |
| BuildOak, new shared-data fit | 0.626935 | 0.218363 | 1,536 | 63.8935% |

| Contrast | Log-loss difference, 95% interval | Brier difference, 95% interval | Accuracy difference, percentage points, 95% interval |
|---|---:|---:|---:|
| Shared-data Alcaraz minus BuildOak | −0.022913 [−0.032487, −0.013962] | −0.008957 [−0.012578, −0.005537] | +1.6223 [+0.6602, +2.6139] |
| BuildOak shared-data minus full-system | +0.021896 [+0.013259, +0.030979] | +0.008622 [+0.004953, +0.012162] | −2.2047 [−3.6017, −0.8793] |

The original WTA paired bootstrap and all predeclared 4/13-week sensitivities preserve these directions. On the 2,327 completed matches, the controlled log-loss difference is −0.020908 and accuracy difference is +1.7619 points. The models disagree on 367 winners: Alcaraz is correct on 203 and BuildOak on 164. All 2,404 targets receive a native forecast, with no fallback.

The common state history is the accepted WTA01 panel's 41,316 primary records from 2007–2024; 1,169 provisional records remain excluded. Literal missing count blocks stay missing, and 105 invalid blocks are masked. Shared rankings start in 2000, with all 380 records in 190 conflicting player/date groups excluded. That exclusion reproduced the incumbent's complete 42,485-row base feature and label files byte for byte; unchanged BIO sidecars, selector ancestors and selected forecasts justify exact reuse.

Both final heads use the same 10,496 supervised keys from 2019–2023, the same 2023-12-30 fit cutoff, and the same 2,404 targets and D−2 reported-date cutoff contract. Available source metadata is shared, but native row-trait and incumbent BIO transformations differ. Alcaraz keeps its past 2021–2023 candidate/calibration procedure; BuildOak keeps its frozen recipe. Final-head training membership is matched; the selection ancestry and learning computations are not identical. This control therefore compares fixed modeling pipelines, not architecture alone or the best achievable tuning of each family.

BuildOak retains its 800/650-tree weighted global ensemble and 900-tree Hard and International-event specialists. Its existing 15,000-row threshold disables the recent component at 10,496 training rows. The full-system WTA fit used 107,246 rows and six members, including that recent component. The combined change in history, count qualification, ranking qualification, supervised period and resulting activation worsens BuildOak log loss by 0.021896 and removes 53 correct picks. This identifies the joint input-policy effect; it does not attribute the effect to one data field, one historical period, or one model member.

Only one new full empirical variant was fitted. Feature projection took 55.03 seconds and native fitting/forecasting 15.58 seconds, with workers capped at two CPUs and 8 GiB, no network and read-only root filesystems. Earlier partial preparation and execution attempts are retained in the private audit archive. The bounded 256-training-row/16-target entrypoint rehearsal used exposed historical data and emitted no scores; it was not synthetic evidence or a second full variant.

## What the native headlines represent

The author's original saved predictions are separate artifacts. ATP contains 607 rows dated January–March 2026. WTA contains 614 rows: 279 dated October–November 2025 and 335 dated January–March 2026. WTA's saved outputs trace to an earlier recipe than the pinned repository HEAD. Neither native score is an original-author reproduction of our 2024 adaptations.

The original native-label metrics reproduce, but ten ATP labels and one WTA label conflict with official results. The populations also contain impossible same-event rematches. A frozen **targeted label-only sensitivity: partial verified-label rescoring, all other labels unchanged/unverified** retains every original row and probability, including unresolved and phantom rows. It changes only the eleven independently resolved labels.

| Native artifact population | Rows / label flips | Log loss, original → sensitivity | Brier, original → sensitivity | Accuracy, original → sensitivity |
|---|---:|---:|---:|---:|
| ATP 2026 (entire ATP artifact) | 607 / 10 | 0.582052 → 0.583061 | 0.200067 → 0.200111 | 68.5338% → 68.8633% |
| WTA entire artifact | 614 / 1 | 0.615539 → 0.617270 | 0.213341 → 0.214133 | 66.6124% → 66.4495% |
| WTA 2025 partition | 279 / 0 | 0.648609 → 0.648609 | 0.227526 → 0.227526 | 63.4409% → 63.4409% |
| WTA 2026 partition | 335 / 1 | 0.587998 → 0.591169 | 0.201526 → 0.202978 | 69.2537% → 68.9552% |

These are artifact-row statistics, not corrected model performance or unique-match estimates. The ATP label changes slightly worsen proper scores while adding two correct picks; the WTA change worsens both. Earlier bad rows may also alter later state and training. Those effects remain unmeasured by saved-probability rescoring. The full WTA row and its year partitions overlap and are not independent evidence.

The frozen event-edition cluster bootstrap uses 5,000 draws, PCG64 seed 20260922, reset for each population. The ATP log-loss delta is +0.001009 (95% interval −0.004179 to +0.010979); full WTA is +0.001730 (0 to +0.004646). WTA's one changed event is absent from 35.98% of draws. These conditional intervals describe concentration of this fixed correction set, not uncertainty over all unresolved truth or a repaired model.

## What was repaired, and what remains limited

The original code lets the full dataset's last date influence historical Elo K. A retained native-function counterexample changes a 2020 update's K from 39.1038 to 38.7972 solely by extending the future frontier. That demonstrates state dependence, without identifying final-score inflation. The accepted adaptations already use a fixed fit-boundary reference, training-only country vocabulary, neutral target metadata, separately released rankings and chronological replay of late older results.

Fresh synthetic controls exercised those actual adapted paths. Target outcome/count/rank mutations and reversed winner encoding preserve target features; future records are refused; eligible changes affect later state. The repaired late-arrival path equals a fresh chronological rebuild while the planted append-only path differs on ten Elo/streak fields. These controls establish bounded behavior. They do not establish every source date or every possible leakage property.

Both systems have exposed development histories. The original author's ATP loop repeatedly optimizes validation ROC AUC, which measures ordering rather than calibrated probability quality. Alcaraz's candidate and calibration selection uses past years, but the broader research process remains exposed. Neither side receives an invented scalar optimism penalty. The accepted 2024 comparison uses log loss, Brier and accuracy on matched targets, with existing calibration retained and no target-informed retuning.

Reported match dates and D−2 cutoffs are retrospective proxy contracts; they are not verified publication or first-ball clocks. A prospective test remains useful but is outside this audit's completion criteria.

The incumbent also has a rule-provenance limitation. An independent rule-era map matches all **20,615** consumed 2016–2024 rows in its selection/fitting ancestry numerically. Retained first-party rule evidence covers **16,647**; **3,968 ordinary-tour rows from 2016–2017 remain provenance-unresolved** after bounded retrieval. This audit retains the existing BO3/TB7 contract conditionally. It does not call that source gate passed or the provenance defect repaired. There is no demonstrated rule-value change that would justify a corrected fit.

A credible unrun improvement hypothesis is past-only calibration of the native probabilities against a proper-score objective. This audit did not tune that procedure or begin another feature/model search. Original-native state repair remains unmeasured until the exact historical inputs and fitted/environment artifacts can be recovered; contemporary upstream data cannot silently substitute for the original run.

Exact aggregate metrics, all predeclared intervals and artifact hashes are in [the machine-readable audit](buildoak_fairness_audit_aggregates.json). The private archive retains row-level evidence, official result bytes, source-recovery receipts, failed attempts, frozen protocols, forecast commitments and independent reviews. No raw rows, fitted models or private machine paths are included in this repository change.

Independent final review: private archive `BUILDOAK_FAIRNESS_AUDIT_20260922/independent_review/FINAL_NUMERICAL_AND_CLAIM_REVIEW.md`, SHA-256 `2eb0e02c221d6ea4534a3b3170bba6aa3369af13c748a383807b12af31acf844`.
