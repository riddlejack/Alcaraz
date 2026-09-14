# Lane B2 independent review and repair

The different-model review of Fable's `791f020` implementation rejected three integration
claims before the repair: read/write file modes escaped observation; runner-owned stage
records could write through symlinks; and verification trusted cached verdicts instead of
reconstructing access. The [baseline review](equivalence/b2_review/baseline.md) and
[follow-up review](equivalence/b2_review/followup.md) are portable tracked representations
of the independent reports. Their byte-originals and hashes live in `local/evidence/`;
scripts, command logs and full saved-run hash inventory are retained in `local/review_b2/`. These findings concern ordinary
file I/O and local consistency, not a security sandbox or independent holdout custody.

The integrating owner separately reproduced two gaps: the metadata projection returned
target serve statistics, and T2 missed the `datetime64[ns]` counterexample rejected by
archive R28. T2 was repaired in `8f02b8f`; its supported calendar dtype checks include the
same original negative control. Untyped opaque and serialized-text dates remain outside
its declared coverage.

The repair design was frozen before production edits in
`local/review_b2/repair_design.md`. It changes only access evidence and enforcement:

- Audit schema 2 includes read-capable update modes and requires a completion record,
  even when there were no reads. Missing or truncated evidence fails. Existing schema 1
  receipts are retained as historical evidence and cannot pass the new verifier.
- The ledger binds each complete stage manifest; the driver checks output membership,
  digests, stage inventory and exit status. Verification re-derives access against the
  configured declaration and validates fold/year/date horizons and the barrier tree.
- Runner stage/config/filled-config/temporary/log/ledger write paths reject symlinks;
  existing symlink descendants in a stage output directory are rejected before launch.
- Metadata projection uses a closed field set per purpose. SR03 explicitly retains
  played/completed/source-agreement eligibility flags, market quotes and a Boolean
  outcome-resolution flag; none of these is presented as a physical isolation boundary.
  Target serve statistics, status, labels, scores and unknown added fields are omitted.
- Only genuine stage-root bookkeeping files are excluded from metric scanning. Nested
  files carrying the same names are inspected.

The new public-interface controls are in `tests/test_b2_review_regressions.py`.
The different-model follow-up closes the three original defects. It reproduced one
further cutoff-horizon hole, fixed in `907b79e`, and independently checked the same
control after repair. Its 43 targeted tests passed; a retained schema-2 sample verified
under the final date guard (14 stages), and three consistently rebound bad-log controls
were rejected on their actual horizon violations. T2's original R28 counterexample was
independently rejected; 28 calendar-dtype and explicit limitation cases passed.
Fresh historical reconstruction is accepted within the stated numerical/provenance
scope: [review](equivalence/b2_review/reconstruction.md),
[hash-backed summary](equivalence/b2_review/reconstruction.json). Both tour chains and
final verification pass; all 342 forecasts, ten final report files per tour and 210
training-key files match. Permitted signed-zero estimator differences and the residual
WTA workbook modified-time variation remain explicit in `docs/EQUIVALENCE.md`.

The final [native T1 comparator review](equivalence/b2_review/native_t1_review.md)
reproduced two membership omissions and verified their repair in `50d9fba`: every
expected target-year artifact must contain exactly its applicable chosen targets,
without duplicates. Four fast controls catch extra unpriced targets, dropped targets,
duplicates and an empty sibling forecast on both sides. Integrated synthetic checks
are recorded below when complete. No frozen model settings, source horizons or accepted numbers
are changed. Native T1 and the broader RB9 campaign gate have separate dispositions.
