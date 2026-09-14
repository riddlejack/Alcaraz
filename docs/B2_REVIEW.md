# Lane B2 independent review and repair

The different-model review of Fable's `791f020` implementation rejected three integration
claims before the repair: read/write file modes escaped observation; runner-owned stage
records could write through symlinks; and verification trusted cached verdicts instead of
reconstructing access. Original scripts, review, command logs and the saved-run hash
inventory are retained in ignored `local/review_b2/`. These findings concern ordinary
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
Final follow-up review, synthetic checks and fresh historical reconstruction are pending
at this design commit. No frozen model settings, source horizons or accepted numbers
are changed. Native T1 and the broader RB9 campaign gate have separate dispositions.
