# Independent B2 review of baseline 791f020

Reviewer: Codex subagent, independently inspecting the Fable implementation. Read-only tracked-tree review; reproductions use temporary scratch. Baseline review recorded before integrating-owner fixes. Scope: runtime outcome-read declarations, verifier integrity, output confinement and the selection commitment. The original suite is being rerun separately; a green suite does not override the findings below.

## Findings

### P1: read/write file opens are excluded from runtime observation

`src/tennislab/chain/access.py:78-83` skips `O_RDWR` opens and every Python mode containing `+`. These modes allow reading. A stage using ordinary `open(panel, 'r+')` or `os.open(panel, os.O_RDWR)` can read the `a_won` column while a `none` declaration reports no observed outcomes and no violations. This is an ordinary supported file-I/O coverage defect, not a claim about sandboxing an adversarial interpreter.

Reproduced using a fresh subprocess importing `tennislab`, workspace panel `a_won\n1\n`, and access-log environment. With mode `r`, the hook writes a read record and `observed_outcome_access` rejects the `none` stage. With `r+` or `O_RDWR`, the same asserted read succeeds, no log is created, and observed/violations are empty. Script: `<REVIEW_SCRATCH>/reproduce.py`.

Suggested regression: run an otherwise legitimate `none` stage shim with each read-capable mode and require an undeclared-read failure; retain a pure write-only positive control. Record read capability, not whether writing is also possible.

### P1: the runner itself follows symlinks while writing stage records

`src/tennislab/chain/runner.py:1020-1043` creates the stage directory and writes stdout/stderr directly; line 1092 writes the manifest, and lines 629-638 append the ledger. The configured run root at line 1929 uses lexical `resolve_under_root`. These destinations do not use the physical output guard added to module output paths.

Reproduced with an otherwise empty scratch workspace: `run/dummy` links to an outside `immutable` directory; `run_stage(Stage('dummy', None, []), {}, run_root, earlier=[])` succeeds and creates `immutable/stage_manifest.json`. No source data was modified. This violates the brief's immutable-input write-confinement promise even without running a stage module. The same review should include existing child file symlinks under an ordinary output directory.

Suggested regression: reject symlinked run root, stage directory, stage manifest, access log, stdout/stderr and ledger before writes; verify outside sentinel bytes stay unchanged. Validate generated config and filled-config destinations as well.

### P1: verify accepts cached clean status without reconstructing access checks

`src/tennislab/chain/runner.py:1110-1134` loads only `manifest.integrity_violations`, rather than checking recorded reads/receipts against configured stage declarations. The manifest itself is excluded from `hash_tree` at line 600, and `verify_ledger` checks only ledger predecessor links without comparing stage output or manifest digests. Thus a manifest can disagree internally or with actual logged access while verify stays clean.

Minimal reproduction: change only a stage manifest's `outcome_access.violations` to `['forbidden read']`, keep `integrity_violations=[]`; `verify_earlier`, `verify_ledger`, and `verify_integrity` all pass. Outputs and ledger are unchanged. This directly contradicts the claim that verify repeats runtime access checks. Current missing-log behavior also returns empty observations and passes, so the absence of audit evidence is indistinguishable from a stage that read nothing.

Suggested regression: mutate a logged read or fold receipt and leave cached verdicts clean; verifier must reconstruct against configured declarations. Bind and cross-check access logs, receipts, complete stage inventory and completed-stage evidence; detect missing logs/flush evidence, invalid exit status, manifest/ledger/output-map inconsistencies and changed barrier run-tree digests. This establishes reproducibility/consistency of local receipts, not independent custody against wholesale history replacement.

## Other scoped limits examined

The barrier names CSV/CSV.GZ/JSON/JSONL as its inspection scope and explicitly documents unknown formats and unknown metric keys. That is a stated limit, not by itself a new implementation bug. The skip of any nested file named `stage_manifest.json` or `access_log.jsonl` deserves narrowing to the genuine stage-root bookkeeping paths: current basename skipping also exempts a module-created nested metric artifact with either name.

The reviewer has not yet completed selection-commitment arithmetic or the original positive/negative regression rerun. The integrating owner independently identified metadata projection returning serve/status fields and is investigating that separately; this report does not claim to have independently reproduced that finding.

## Baseline disposition

Do not close R9/RB11 or describe the verified barrier as complete at 791f020. The implementation substantially improves visibility and moves metrics behind the report barrier, but the three reproduced gaps require repair and independently checked regressions. Native T1 coverage and scientific acceptance are separate gates.

## Completed independent baseline checks

`uv run pytest -q tests/test_barrier_gate.py tests/test_config.py --basetemp /private/tmp/b2-independent-pytest` exited 0: 21 tests passed. This reran the original clean synthetic chain, declared-access positives, four-format metric writer negatives, undeclared reader, fold-receipt negatives, forged criterion/non-argmin negatives and existing symlink path tests. The uncovered bugs above demonstrate gaps in those existing tests, rather than failures of their advertised individual controls.

The selection arithmetic was independently recalculated with Python `csv`, `json` and `math` only; no production pipeline/report numerical function was called. Using the persisted selection keys, raw forecasts, labels, market probabilities and reported slopes, the script rebuilt annual logistic losses and equal-year means and evaluated the slope objective derivative. All 15 fits (12 candidate fits across 6 decisions and 3 market fits) matched the published losses within 1.1102230246251565e-16; the maximum absolute objective derivative at the published slope was 2.5460536456911598e-14. All six selected candidates were the independently computed argmin. Script: `<REVIEW_SCRATCH>/selection_arithmetic.py`. This checks the sample's arithmetic and stationary optimum, not source truth, historical WTA receipt completeness or prospective validity.
