# Lane D repair contract

Status: **frozen before implementation against the rejected slice ported as `954f449`**.
The original design and freeze record remain as evidence of the failed attempt. This
repair changes engineering and information-boundary enforcement only: no model setting,
fit, candidate selection, historical score or real forecast changes.

Source rejection: archive `LANE_D_reconstruction.md`, verdict at `50518be`. The
reconstruction reproduced the synthetic Elo arithmetic and ledger transitions but found
that bound history bypassed the four-time eligibility rule, a named timezone did not
control the local cutoff, mutable receipts and fixture files were not authenticated,
source status was checked without required fields, write IDs could escape the live
workspace, and the tracked test helper failed repository hygiene.

## Repair contracts

1. **Bound history uses the same eligibility vocabulary as incremental rows.** Every
   history CSV carries the original source date and `date_basis`, plus
   `completion_upper_bound`, `completion_basis`, `publication_upper_bound_utc`,
   `receipt_time_utc`, `status`, and `overlap_unresolved`. A binding declares the
   admissible completion bases. A row enters state only when its completion basis is
   admitted, its completion bound is on or before the fixture cutoff, publication and
   receipt are on or before issue, it is played, and overlap is resolved. Elo orders the
   admitted row on the completion upper bound, never on an unqualified source date.
   Lineage counts every exclusion reason separately.
2. **Receipt and retrospective availability remain different facts.**
   `receipt_time_utc` proves when these bytes entered local custody. It does not prove the
   result was historically available then; `publication_upper_bound_utc` is the separate
   availability evidence. Both gates must pass. An acquisition receipt is bound into a
   version manifest by path, SHA-256, source/attempt identity and finished time, and is
   reverified before any version is used.
3. **The named timezone controls the calendar cutoff.** The scheduled instant must have
   an explicit offset, the timezone must be a valid IANA name, and the local date is the
   instant converted into that zone. Invalid zone names are excluded; an input timestamp's
   displayed calendar date is never used as a substitute.
4. **Fixture qualification binds bytes and identity.** A batch manifest hashes
   `fixtures.jsonl`. Forecast verifies that hash, the batch/version identifiers, the
   recomputed stable fixture id, and the immutable qualification payload already in the
   ledger before reading the row as a forecasting subject. Changing the file, or changing
   it together with its manifest, must still fail.
5. **Source qualification is field-level.** Each public adapter checks both its allowed
   status and every field it consumes. A source-wide `qualified` label with a missing
   required field is refused before acquisition or ingest.
6. **Every live path is confined for writes.** Live paths pass the product's physical
   symlink check. User-supplied batch, version and settlement IDs are one conservative
   path segment: ASCII letters/digits followed by letters/digits, period, underscore or
   hyphen; absolute, traversing, empty and separator-bearing values are refused.
7. **The synthetic helper obeys product hygiene.** Tests locate their repository from the
   test process working directory, not from the source file's parent chain.

## Public negative controls

All controls invoke `tennislab.cli.main`; test setup may plant or hash a file, but no
internal enforcement method is the subject of the assertion.

- add one otherwise valid bound-history row with, in turn, a late completion bound, late
  publication, late receipt, non-played status, unresolved overlap or an unadmitted
  completion basis; each row is withheld with the named lineage reason;
- issue a `00:30Z` fixture in `America/Chicago`; its local date is the preceding day and
  therefore its D-2 cutoff is one day earlier than a UTC-derived cutoff; an invalid IANA
  zone is excluded;
- edit a bound acquisition receipt after update; fixture/forecast use is refused on the
  receipt hash mismatch;
- edit qualified fixture bytes; forecast refuses the file hash; then update the mutable
  batch manifest to that new hash and verify the ledger-bound identity still refuses it;
- remove a required field from an otherwise qualified source and run the public update;
- pass an absolute or traversing settlement id and place the ledger directory behind an
  escaping symlink; each public command refuses without writing outside the workspace;
- run the tracked hygiene test and the full repository check.

These are engineering controls, not evidence that a source statement is true, a result
was historically available, or the model has prospective value. The TML snapshot/date
decision is outside this repair: per rebuild R32, a supplied TML date is not admitted as
an unconditional completion upper bound until the recorded negative offsets and the
missing official check are resolved. D2 must quarantine unresolved chronology or bind a
separately corroborated completion bound.
