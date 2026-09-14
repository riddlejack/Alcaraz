# Process

This page is a placeholder for the narrative of how the research loop worked. The
roadblocks section below is the archive's own register of every recorded failure and the
rule now in force, copied from `docs/reviews/rebuild_2026-09-13/SCAR_TISSUE.md` at the
archive commit named in `ARCHIVE.md`. The 'Enforced by' column names the rebuild lane.

## Roadblocks


Compiled 2026-09-13 from the decision record, the three adversarial reviews, the experiment and exposure ledgers, run records and handoffs. Each row names where the evidence lives, the rule now in force, and which lane enforces it. Lane briefs cite rows by number. This file also becomes the "roadblocks" section of the product repo's PROCESS page.

Severity: **P0** would invalidate a headline claim; **P1** would materially change a number or its interpretation; **P2** cost time or credibility.

## A. Chronology and information sets

| # | Sev | What happened | Evidence | Rule now | Enforced by |
|---|---|---|---|---|---|
| A1 | P0 | Draw-page rows for June–September 2026 had no match date. The chain invented one (event start plus one day per round) and labelled it as a reported date. A Canada final was dated four days early, and its result entered two later Cincinnati targets' Elo features. | Astra review finding 1; D60; `AUDIT-ASOF-CONTRACT-ATP.md` | Every date carries a typed `date_basis`. Inferred dates are bounds at the event's end, never clocks. A provenance label may never be attached to an invented value. Future-mutation test on every feed. | B (types), C (T1, T2, T5) |
| A2 | P0 | Even with event-end dating, overlapping events leak forward: Toronto ends 08-13, Cincinnati starts 08-10; about 85 Cincinnati rows consume a Toronto result that postdates them. | D62 | Overlapping weeks need per-match dates; until acquired, the rows are flagged and excluded from cutoff-sensitive features. | A (per-match date qualification), C (T2) |
| A3 | P0 | Satellite circuits (four component draws sharing one start date) were released at anchor + 7 days; Spain 1 2006 ran to 03-26 but all legs were dated 03-06. 911 circuits, 110,681 rows. | Astra finding 3; TIER01 attempt 002 | Multi-leg events are dated at the last possible completion, anchor + 7 × legs. The Spain 1 2006 case is a regression test. | B (chronology module), C (T2) |
| A4 | P0 | The TIER01 debut-rating offset (−117) was learned on data through 2016 and applied to rows inside 2014–2016 selection folds. | Astra finding 4; TIER01 attempt 002 | Every learned constant has a receipt naming its data horizon; the horizon precedes the earliest row it touches; per-boundary re-estimation when needed. | B (ratings receipts), C (T9) |
| A5 | P1 | Same-event qualifying rows updated the tournament latent term used by later main-draw predictions in the same event; the design did not declare this channel. | Astra finding 8 | Every information channel into a stateful feature is declared in the design and ablatable. | B (design template), E |
| A6 | P1 | The D−2 cutoff excluded every previous-day match, which is where acute fatigue lives; FAT01's null was then read as a fatigue null. | Astra finding 10; D57 | The cutoff is a declared design parameter. A feature is evaluated under the cutoff the live system will actually use. | A (date quality), E |
| A7 | P1 | Reported calendar dates have no clocks; annual Pinnacle prices are closing-like with unknown quote times. Model-versus-market comparisons were sometimes written as if equal-cutoff. | D31; leaderboard notes | Market comparisons are labelled descriptive unless both clocks are known. The prospective ledger records receipt times for both. | D, docs |
| A8 | P1 | Tennis Abstract's published court-speed index uses the whole year, so using it as a feature leaks. | Fable review 2026-09-10 | Any index computed over the target event's matches is a validation target, not a feature; build point-in-time versions in-house. | E |

## B. Barriers, exposure and confirmation

| # | Sev | What happened | Evidence | Rule now | Enforced by |
|---|---|---|---|---|---|
| B1 | P0 | The SR03 calibration stage loaded labels and wrote reserved-year scores during CONFIRM2026 attempt 005, before the end-of-chain barrier. The final barrier could not stop an upstream scorer. | Astra finding 2; exposure log | Only the report stage can open labels; every earlier stage runs with the label file physically absent; a test makes labels unreadable and asserts every pre-report stage still completes. | B (module boundary), C (T8) |
| B2 | P0 | Five chain attempts on the reserved window failed mechanically (paths, calendar-cell parsing, event-name mapping, stage order, output guard) because workers could not see the reserved inputs and guessed formats; fixes happened after first outcome access. | exposure log; handoff 2026-09-11; memory | Structural probe of real inputs (columns, types, counts; no players or scores) before any parser is written. Dry-run and full rehearsal on exposed years with the exact command before a real run. | all lanes |
| B3 | P0 | 2025–2026 was the only reserved window; it is now spent and degraded (a third of 2026 rows rank-stale, states a median 37 days stale). | D52, D60, RESERVED01 | No historical window is confirmation. Confirmation is prospective, with fixture universe, update policy and stopping rule declared in advance. | D |
| B4 | P1 | Design said probability-space blending; code did rating-space blending (ELO-DATE-002). Found only by independent arithmetic. | D27 | Design and implementation are reviewed against each other by a different model before freeze; a closed-form fixture pins the exact arithmetic. | B, reconstruction threads |
| B5 | P1 | A run manifest recorded the SHA-256 of `{}` as the run-tree digest and nobody noticed. | Astra finding 12 | Manifests reject empty or placeholder digests; verification re-hashes the tree. | B (chain), C (T10) |
| B6 | P1 | Copied reporters hard-coded the primary contrast and seed; FAT01's machine artifact attached the wrong bootstrap to the wrong contrast. | Astra finding 12; handoff item 5 | The primary contrast, seed and interval type are configuration, read by one parameterised reporter; a test asserts the artifact names match the config. | B (evaluation) |
| B7 | P1 | The conditional-selection risk regression could predict a log-loss advantage outside the range either outcome permits; it selected 6,101 matches even when the market was stipulated exactly correct. | TEACHER03/04; D69 | Any decision rule gets a label-free diagnostic under a "market is exactly right" world before use. | E |
| B8 | P2 | 145 leaderboard entries and 113 ledger entries over the same 2017–2024 window; readers cannot see selection risk. | assessment §3.2 | A research-degrees-of-freedom summary is generated with every leaderboard. | B (evaluation), docs |

## C. Source qualification and coverage

| # | Sev | What happened | Evidence | Rule now | Enforced by |
|---|---|---|---|---|---|
| C1 | P0 | Upstream Sackmann repositories were deleted (last full visit 2026-05-08); tennis-data.co.uk returned 503 on all direct requests; the fallback was Wikipedia draws with no stats and no dates. | RES2026.md; SRC02.md | Every source has a preserved mirror, a named fallback and a monthly liveness probe. A fallback with weaker semantics is typed as such and cannot silently replace the primary. | A |
| C2 | P1 | Serve statistics are absent by era and family: ATP Challenger/qualifying before 2010, ATP Futures entirely, WTA before 2016 in full form (service games missing 2003–2015), lower tiers after May 2026. | TIER01-audit.md | A coverage matrix by tour, year, level and field is maintained and versioned; features declare the eras they are valid in and carry missingness indicators. | A |
| C3 | P1 | The WTA 2016 floor discarded 1,535 usable earlier blocks; a missing service-games field made whole rows "unusable" when 16 of 18 counts were present. | Astra finding 11 | Adapters accept partial blocks with explicit per-field missingness; floors are declared before results, never chosen after. | A, B |
| C4 | P1 | SR01's service-count qualification was revoked after missed internal constraints. | README source limits | Qualification means an explicit constraint list, tested (e.g. first-serve-in ≤ service points; points won ≤ points played). | A |
| C5 | P1 | Four `best_of` fields were wrong in the archive; the raw source age field was defective; `ServeNumber` changed meaning by year in point files. | D37, BIO01, D43 | Never trust a column name across years; per-field, per-year contracts with corroborating official documents; corrections are new versions with receipts. | A |
| C6 | P1 | 2009 WTA odds files lack Pinnacle columns; a 2018 ATP odds file needed recovery; RES2026's first Wikipedia attempt failed on URL encoding (37 superseded receipts). | WTAODDS01; Astra reconciliations; RES2026 | Coverage matrices per source, year and field precede use. Failed attempts keep their receipts. | A |
| C7 | P1 | Retrospectively revised annual workbooks and current player tables have no historical publication custody; DOB and height tables are current snapshots. | JOINT04-features.md | Custody status is a typed field on every source; "no publication clock" is stated in every result that depends on it. | A, docs |
| C8 | P2 | Data downloaded in 2026 was at risk of being described as if it were a 2024 system receipt. | ARCHITECTURE.md clocks section | Event, availability, receipt and decision times are separate fields; a later download supports historical analysis only with external availability evidence. | A, B |

## D. Engineering and reproducibility

| # | Sev | What happened | Evidence | Rule now | Enforced by |
|---|---|---|---|---|---|
| D1 | P1 | Freezing by copying whole pipelines produced 27 byte-identical file groups, 165k Python lines and 55 files over 1,000 lines. | assessment §1 | Freeze by git tag plus manifest hash. One trunk, configurations per model. | B |
| D2 | P1 | 135 of 295 tracked scripts read from the ignored 20 GB `work/`; 22 files carry absolute paths; no dependency spec, lockfile or CI. Nothing runs from a clean clone. | assessment §1 | Product repo installs from a lockfile and reproduces one headline number from a committed sample in CI. No tracked code reads outside the repo except declared data roots. | B |
| D3 | P1 | A relative-path error in MULTI03's frozen reporter; SR02's first numerical run failed to converge; both had to be repaired under new identifiers. | ARCHITECTURE.md | Runs execute from the repo root with config-only paths; numerical adapters emit convergence receipts; failures are preserved. | B |
| D4 | P2 | Documentation drift: README said 105 entries when there were 134; "largest sports gain" was wrong; `experiments/README.md` still says no study has run; TIER01.md says attempt 002 was not reconstructed while D63 says it was; "Rust-first" describes nothing current. | Astra finding 13; assessment §3.4 | Numbers in docs are generated from registries; a consistency check runs in CI; status prose is replaced, not appended. | B (docs), Lane 0 |
| D5 | P2 | The leaderboard summary placed a sports score on all targets beside a market score on the priced subset; the WTA/ATP comparison mixed equal-year with match-weighted means over different year spans. | Astra findings 6, 13 | One summary path; paired populations only; estimand named in every table header. | B (evaluation) |
| D6 | P2 | Nine-decimal deltas and several interval types, with the wider one sometimes chosen after seeing results. | Astra conceptual critique | Four decimals; one pre-declared interval type; dependence caveats stated once. | B (evaluation), docs |
| D7 | P2 | Workers were barred from reserved files and guessed formats (see B2); long single-agent builds shipped defects that a fresh-context review caught. | handoff 2026-09-12 rules | Structural probe first; fresh-context implementation review before any freeze. | all lanes |
| D8 | P2 | Credentials were correctly kept out of Git at `~/.config/tennis-research-lab/credentials.env`. | handoffs | Keep it. Never in Git, logs or process arguments. | all lanes |

## E. Interpretation and claims

| # | Sev | What happened | Evidence | Rule now | Enforced by |
|---|---|---|---|---|---|
| E1 | P1 | "The women's market is not less efficient" was written from a model-minus-market gap; the gap depends on model quality and coverage, not market efficiency. | Astra finding 6; D60 | A model-minus-market gap is a statement about the model. Market-efficiency claims need equal-cutoff prices and a separate design. | docs, E |
| E2 | P1 | TIER01's primary bundled several changes; the report claimed "opponent information rather than more rows", which the design could not identify. | Astra conceptual critique | Mechanism claims need a planned decomposition; a bundle result is a bundle result. | E |
| E3 | P1 | "8 of 8 years" was read as eight replications; five residual designs were called five confirmations. They share data and ancestry. | Astra conceptual critique | Years are robustness evidence, not replications; state the dependence once per table. | docs |
| E4 | P2 | Acquisition success (bytes preserved) was described as measurement readiness. | Astra finding 14 | "Acquired", "qualified" and "modelled" are three statuses. | A, docs |
| E5 | P2 | The first review found the project mining a single 2,595-match season and treating Rust as a scientific choice. | Fable review 2026-09-10 | Walk-forward over the full history; engineering choices described as engineering. | B |

## Red-team questions to re-ask at every acceptance

1. Can any feature be historically valid yet unknowable at the forecast time?
2. Would shuffling rows within an event change any feature? If yes and only event dates exist, chronology is invented.
3. Does re-running after a correction change old features? Then the original result is not reproducible.
4. Does the result survive the strongest same-time baseline and the whole family of attempted specifications?
5. Do the row counts and every exclusion reason reconcile to the declared universe?
6. Does a number in the README trace to a generated table?
