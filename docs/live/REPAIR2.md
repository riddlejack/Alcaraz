# Lane D second repair-attempt contract

Status: **frozen before controls, implementation, or verification against the rejected
repair `542d85e`**. `docs/live/REPAIR.md`, `REPAIR_FREEZE.json`, the failed source and
port, both reconstruction reports, and their retained counterexamples remain evidence.
This attempt is limited to findings F1-F3 in `LANE_D_REPAIR_RECONSTRUCTION.md`. It does
not implement D2, acquire a source, create real history, fit a model, issue a real
forecast, or claim adversarial process sandboxing.

## Repair contracts

1. **A qualified version means an exact manifest digest.** Fixture qualification records
   the SHA-256 of the exact `versions/<id>/manifest.json` whose files and acquisition
   receipts verified at qualification. The digest remains in the hash-chained fixture
   qualification and its batch row. Forecast loading requires both the qualified
   `version_id` and that exact manifest digest. A known fixture continues to use both
   values from its original qualification.
2. **Explicit settlement version loading has a prior trust anchor.** `settle results
   --version <id>` accepts a version only when its manifest digest is still the digest in
   the unchanged latest pointer or an existing fixture qualification for that version.
   The default `latest` route keeps the same pointer check. Rehashing a receipt and the
   mutable version manifest after either trust assignment must fail. A hash proves only
   that bytes are unchanged since that assignment; it does not prove source truth,
   publication truth, or independent custody.
3. **The actual write leaf is checked.** Forecast output and proof-request paths pass the
   same physical live-workspace check as their directories, including dangling leaf
   symlinks, and use exclusive creation for new single-write files. Existing passing
   directory, pointer, ledger, identifier, and ordinary-write behavior stays in scope.
4. **Atomic temporary files are unpredictable and exclusively created.** The shared
   `chain/common.py` JSON and CSV writers use a standard-library secure temporary file
   in the destination directory followed by the existing atomic replacement. They
   refuse a symlink at the final leaf and clean up an uncommitted temporary file. This
   is the only authorized shared-writer change: serialization, fsync, returned SHA-256,
   replacement semantics, all numerical logic, and all caller interfaces remain the
   same. It is output confinement, not a general race-proof or hostile-process sandbox.
5. **Malformed timestamps use the declared typed failure path.** Invalid ISO timestamp
   text becomes `LiveError`. Fixture construction records `start_unparseable` for that
   row and continues through the public command without a traceback or qualification.
   Valid offset-aware timestamps, named-zone conversion, and equality boundaries remain
   unchanged.

## Public controls frozen for this attempt

Every control invokes `tennislab.cli.main` through the tracked synthetic workspace.
Test setup may retain and coherently rehash the planted mutable files but does not call
an internal enforcement helper as the subject of the assertion.

- qualify a fixture, retain its ledger and batch bytes, edit the bound acquisition
  receipt's `finished_utc`, and coherently update only that receipt binding in the
  version manifest; `forecast` must refuse on the qualified manifest-digest mismatch;
- update a version, retain its latest pointer, edit the receipt and coherently rehash
  the version manifest, then call explicit `settle results --version <id>`; it must
  refuse against the pointer's prior digest;
- after valid qualification, plant dangling symlinks at `forecasts.jsonl` and at the
  predictable proof-request leaf in separate worlds; each public forecast must fail
  without creating the synthetic outside target;
- before replay update, plant the formerly predictable
  `latest.json.tmp.<pid>` symlink; the command may use a different secure temporary but
  must not write the outside target, and its resulting latest pointer must be a regular
  file;
- submit one malformed `scheduled_start`; public fixture output must record exactly the
  typed `start_unparseable` exclusion with no traceback and no qualification;
- retain positive update, fixture, forecast, proof, explicit-current-version settlement,
  cutoff equality, named-zone, receipt equality, numerical equality, and chain behavior;
  run focused live/hygiene tests before the final required `make check`.

Acceptance remains independent. A green builder suite does not accept this attempt or
close D2, source qualification, historical availability, scientific validity, or
prospective value.
