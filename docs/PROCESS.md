# Process: build it, try to break it, keep the evidence

## Current operating policy — September 16, 2026

This section governs how future work is organized. The history below explains
earlier controls; it is not a requirement to repeat every review. Existing
frozen attempts, explicit user stopping points, and experiment-specific
approvals remain binding. This policy does not reopen or approve Bundle A
scoring or reuse of rejected outputs.

Research progress includes valid negative and inconclusive findings. A completed
experiment may reject a model; a completed forecasting capability must
demonstrate its intended successful path on admissible inputs. Preserve
evidence needed for reproducibility and claim validity, but do not create
another review, receipt, or handoff unless it addresses a specific unresolved
question or changed dependency. Keep partial capability explicitly partial.

Use one implementing owner for a bounded outcome. An authorized development
experiment normally includes preparation, execution, evaluation, and one result
review in the same task; its prediction commitment remains an internal enforced
stage. Stop earlier when the user or registered contract explicitly requires it.
Delegate a specific deliverable when useful, then wait for completion or an
actionable exception; avoid repeated status interrogation or parallel duplicate
inspection.

Distinguish three cases:

- **Routine code, path, environment, or documentation repair:** inspect the
  affected behavior, apply the fix, and run focused checks. Reuse unaffected
  accepted evidence. Do not add a scientific design review merely because a
  launcher or document changed.
- **Exposed development experiment:** specify the question, data, cohort,
  cutoffs, menu, selection, and comparison once, then execute to its authorized
  endpoint. Report all attempted alternatives and the exposure honestly.
  Repeated review cannot turn exposed work into prospective evidence.
- **New scientific claim, changed chronology, cohort, features, or model
  selection, or prospective or confirmatory work:** review the affected
  scientific design before execution and independently check the material
  claim. Extend review only for a concrete unresolved objection. Do not reopen
  unrelated accepted components.

Routine runs of an already accepted procedure reuse its review unless a
relevant dependency changes or the procedure's contract requires another
review. Prospective issuance alone does not require a new scientific review.

If qualification materially reduces coverage, reassess what the remaining
sample can answer before investing in execution and interpretation. A narrow
development diagnostic deserves bounded effort and a narrow claim.

Before freezing a new executable attempt, rehearse its actual entrypoint in a
fresh process with representative synthetic or permitted exposed data. Exercise
the working directory, environment set before imports, configuration loading,
declared membership receipts and bindings, output location, failure logging,
commitment, and read-only verification. A metadata scan alone is not an
execution rehearsal. This check does not authorize a restricted fit or crossing
an existing score barrier.

Keep the scientific specification separate from execution receipts. A technical
repair receives a concise delta: what changed, which outputs or dependencies are
affected, and which checks establish the repair. Preserve failed attempts and
changed-code provenance; use a new execution record where required. Reuse
numerical artifacts only when their inputs, semantics, and validity are
demonstrably unchanged and the attempt's contract permits reuse. A changed
scientific design needs a new registered version. Unknown impact requires
investigation, not blanket reuse or recomputation.

Verification must not rewrite the evidence it verifies; write diagnostics to a
different path. Required approval must come from the designated reviewer or
owner and identify its scope. Passing tests, checklist text, and builder-written
status are not approval. When the same launch path fails repeatedly, repair and
rehearse that path before creating another freeze or review cycle.

Past-only fitting, calibration, and selection objectives are legitimate training
computations. They are distinct from target evaluation; existing artifact-format
and report-barrier restrictions still apply. Keep each fold's target labels out
of that fold's fit and selection access, preserve chronological source
availability and frozen inputs, and report exposure, matched comparisons,
failures, and negative results honestly.

For current acceptance, follow the relevant decision in `docs/DECISIONS.md` and
its linked route or experiment evidence. A dated global warning is not a verdict
on every later scoped result. One accepted synthetic route does not establish
another route, source truth, or prospective validity.

The first version of this project produced plausible model results. Reviewers then found
that plausible was not the same as trustworthy: dates had been invented, one learned
constant could see the future, a calibration stage scored before its barrier, and an
all-green leakage suite missed planted defects. The project became useful when those
failures were kept rather than edited out.

The result is two related artifacts:

- a research archive containing designs, attempts, failures, exposure records, source
  receipts, and reviews; and
- this smaller product repository, which rebuilds the accepted retrospective chains as
  one Python trunk with reproducible configurations and scoped integrity controls.

Passing tests establishes only the behavior those tests exercise. The tennis findings
remain retrospective, and the live/snapshot path remains unfinished.

## The human–LLM operating model

The owner set the research question, scope, licensing and source-use boundaries, kept ATP
and WTA in scope, chose when to stop or reopen work, and required failed attempts to stay
visible. The work was then split by role:

- **Claude Fable 5.1** led the research build, wrote designs and decision records, ran the
  experiment program, planned the rebuild, and implemented the first product trunk.
- **GPT-6 (Astra)** performed adversarial and acceptance reviews, including the review
  that found the chronology and barrier failures.
- **Claude Opus 4.8** handled bounded Jeff Sackmann / Tennis Abstract acquisition probes
  under explicit traffic and write limits.
- **OpenAI Codex** reconstructed accepted outputs, reviewed integrity repairs, integrated
  the B2 product work, and recorded the limits that remained.

The point was not a relay race between chat windows. One integrating owner issued narrow
briefs with evidence roots, read-only inputs, write boundaries, acceptance tests, and
stop conditions. Builders did not accept their own consequential claims. A different
model received the report and repository, re-derived the important numbers, and tried to
produce counterexamples.

## Historical rebuild practice: the contract that emerged

The September 2026 rebuild used the historical workflow below. Future work
follows the current operating policy above while preserving the rules of frozen
attempts.

1. **Pre-register the question.** Name the population, cutoff, information set, fitting
   and selection process, baselines, primary contrast, uncertainty method, and stopping
   rule before the target outcomes are read.
2. **Probe structure before writing a parser.** Inspect columns, types, and counts without
   exposing player identities or scores. Rehearse the exact command and output class on
   development data.
3. **Freeze one attempt.** Hash the configuration and inputs. A changed method gets a new
   attempt identifier; it does not overwrite the old one.
4. **Run with receipts.** Stages record code and input bindings, outcome-read receipts,
   output hashes, and a linked chain ledger.
5. **Enforce the report barrier.** Fold-specific past outcomes may be read for fitting,
   but no target-year score may be emitted before the post-barrier evaluation stage.
6. **Plant a failure before admitting a detector.** A leak check must reject the defect it
   claims to detect. A green check without that counterexample stays diagnostic.
7. **Reconstruct independently.** A different model reproduces the arithmetic and the
   relevant bytes, challenges interpretation, and records exceptions rather than
   normalizing them away.
8. **Count exposure.** Every look at a development target is logged. Nothing repeatedly
   inspected becomes a holdout because a folder is called “reserved.”

## What reviewers caught

The archive's `SCAR_TISSUE.md` is the complete register. These were the failures that most
changed the project.

| Failure | Consequence | Rule or repair |
|---|---|---|
| Draw-page rounds were converted into invented match dates and labelled “reported” | A 2026 Canada final entered two later Cincinnati feature rows | Every date has a typed basis; anchors are identifiers or bounds, never clocks |
| Toronto and Cincinnati overlapped | Event-end dating alone could not order about 85 target rows | Unresolved overlaps are quarantined until completion evidence is admissible |
| Four-leg satellite circuits were released after one week | Lower-tier history entered too early | Completion is bounded by the whole circuit; Spain 1 2006 is a regression case |
| A −117 debut offset was learned through 2016 and used inside 2014–2016 folds | Selection data influenced a supposedly past-only constant | Every learned constant carries a horizon receipt preceding its use |
| SR03 wrote scores before the final barrier | A downstream barrier could not stop an upstream scorer | Current trunk emits forecasts before the barrier and computes components after it |
| 145 leaderboard entries and 113 experiment-ledger entries accumulated | A clean final table could hide the search history | The generated ladder reports degrees of freedom and all results are called exposed |
| The first leakage suite passed 24 checks, then several planted leaks passed too | “All green” was not evidence of comprehensive coverage | A detector enters CI only after its negative control fails as intended |
| Whole pipelines were copied to freeze them | 27 byte-identical groups, 165k Python lines, laptop-only paths | One trunk, model configurations, a lockfile, synthetic fixtures, and manifest hashes |
| Tables mixed all-target sports scores with priced-subset market scores | Apparent comparisons used different populations | Paired comparisons use identical cohorts and name the estimand in the header |
| Nine-decimal deltas and multiple interval types encouraged over-reading | Presentation implied more certainty than the design supported | Four decimals and one declared interval method, with its missing uncertainty stated |
| A model–market gap was described as market efficiency | The design identified model performance, not market structure | Market comparisons are descriptive until quote and forecast times align |
| Eight years were called eight confirmations | Shared players, data, and model ancestry were ignored | Years are robustness evidence, not independent replications |

Not every correction changed a score. The corrected ATP lower-tier run's registered
equal-year `full_tier − full` delta moved from −0.0067 to −0.0068 on the same 18,972
all-target matches. The sports result survived; the earlier claim that its process was
leak-free did not. Both outcomes remain in the registry.

## From archive to one trunk

The production-readiness review found that the research archive was not a product: many
tracked scripts depended on an ignored 20 GB work directory, absolute paths were common,
and no clean-clone environment or CI contract existed. The rebuild kept the archive as
evidence and ported only the accepted path into a Python package.

The scoped B2 repair was consequential. An independent reviewer first reproduced read
escapes, symlinked writes, cached-verdict trust, incomplete target membership, and an
additional fold-cutoff defect. The integrating owner repaired them, then a fresh
reconstruction checked the result. At `f659114`:

- 206 ATP and 136 WTA forecast files matched;
- 20 final report files matched;
- 210 training-key files and membership hashes matched; and
- the local suite reported 434 passing tests and one optional archive-dependent skip.

The exceptions are part of the evidence: fitted estimators can differ at signed-zero and
pickle-memo bits without changing predictions, and WTA workbook metadata creates a
documented source-hash cascade. “Byte-identical” is used only for the files that actually
matched. The B2 checks are not comprehensive source truth, scientific validity, or
independent custody.

## Research comparison, including the nulls

On matched priced cohorts, each statistics rung improved over the one below it, and the
normalised Pinnacle line remained better. That is the front-page result. The archive also
preserves attempts to add market residuals, weather, and fatigue:

- MULTI02's small improvement against its calibrated-price control had an equal-season
  interval crossing zero.
- MULTI03 selected a fallback equivalent to the calibrated market.
- JOINT05 was slightly worse than its calibrated-market baseline.
- TEACHER04 failed all scientific gates and promoted nothing.
- WX11's exact weather block made forecasts worse.
- FAT01's exact fatigue block was null.

These are negative or inconclusive results for specific designs. They are not proof that
weather, fatigue, or public statistics can never help. Likewise, losing to Pinnacle does
not decide whether tennis-lab is stronger than other public statistics-only models. The completed
[ranking/Elo benchmark](benchmarks/G_L_RESULTS.md) now supplies a narrower, independently
reconstructed comparison: the incumbent beats all five admitted implementations on both
tours. It retains differing histories, historical timing limits, and excluded stronger
model families; it does not establish universal leadership.

## How the live workflow earned scoped acceptance

The first manual update/forecast/score implementation passed its synthetic arithmetic but
failed independent reconstruction. Five ineligible history cases entered state; a named
timezone was ignored; receipt and fixture bytes were not fully bound; required field
qualifications could be bypassed; and absolute identifiers or symlinks could escape the
workspace. The clean-clone test also failed.

That commit remains rejected evidence. A first repair at exact commit
`542d85e7c0c4e495e582bdbc0201a8a8001a1831` passed its builder's full local check (464
tests passed, one optional skip; base and tier synthetic deltas unchanged) but failed
independent review: its version manifest was a mutable trust anchor, and leaf/temp symlink
writes could escape the intended output boundary. A second repair at `4295df4` closed
those write escapes but still let settlement trust a coherently rewritten current pointer
instead of the earlier ledger qualification.

The final targeted repair at `5089b24` reconciles every prior qualification before
accepting a current pointer, on both explicit and default settlement paths. Independent
review accepted it after 36 adversarial/positive controls and 62 affected tests. The
rejected attempts and contracts remain visible in [the live workflow](live/README.md).
Only synthetic Elo issuance is demonstrated. D2 must separately assemble qualified real
history and all six tour-appropriate rungs into a versioned snapshot.

## Limits of the current release

The current release is a historical research artifact with trained model checkpoints.
A complete live prediction application would additionally need the real-history snapshot
and all six configurations connected through the accepted manual-workflow contracts.
The ongoing Tennis Abstract collection is not yet a qualified input to these models;
TennisMyLife date disagreements and WTA tier/full-bundle coverage remain explicitly open.
Those limits do not turn the current release into a live forecasting service.

External comparative claims stay within the completed five-baseline benchmark. Each
integrated code release still needs its own hosted CI result. No batch of real forecasts
has yet been verified as issued before play and then scored under a predeclared plan.

## What transfers beyond tennis

The reusable artifact is the discipline: separate event time from publication and receipt
time; separate source acquisition from qualification and model use; preserve negative
results; make every summary trace to a machine artifact; require a planted counterexample
for an audit; and let a fresh reviewer challenge both arithmetic and interpretation.

That is a stronger demonstration of LLM-assisted engineering than a spotless story would
have been, because the record shows where the system failed and what evidence changed the
rules.
