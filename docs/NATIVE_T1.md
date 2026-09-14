# Native future-outcome invariance (B2)

Design frozen before native comparison runs, 2026-09-14. This is a synthetic software
acceptance experiment, not prospective tennis evidence. The original base and tier
samples, their parameters, and their pinned scores stay unchanged.

## Population and intervention

Use temporary copies of the committed synthetic samples. ATP uses `sample_tier` and
the actual five-bundle tier chain. WTA uses a test-local translation of the base
synthetic world: WTA archive member names, best-of-three ordinary WTA rules, and the
native WTA chain. It is synthetic WTA branch coverage, not a reconstruction of women's
tennis. The product has no WTA tier chain; WTA tier coverage remains open.

Freeze the target date at 2020-01-08 and its D−2 eligibility cutoff at 2020-01-06.
Compare every target on that date (chosen by calendar alone). Mutate only records
strictly after that cutoff; records on the cutoff and earlier must be identical.
This final-year choice keeps all fold-training, selection, calibration, and annual
tier-offset horizons before the intervention. It does not test invariance under a
mutation that legitimately changes a later fold's training set.

The intervention reverses winners while preserving neutral player identities and
pre-match metadata; replaces the full primitive serve-stat block, including missing
blocks, with valid, different counts; changes score, duration, and completion/retirement
status together. Played/walkover/abandoned flags retain ordinary started-match
membership. It does not change eligibility by removing a target from the population.
Panel and tour archive rows receive the same outcome/stat bundle. Lower-tier archive
rows use the stream's corrected reported date, including satellite circuit dating;
only retained, dated lower-tier rows are eligible. Excluded walkovers remain excluded.
Custody hashes are re-bound in the copied input manifests/configs; no fitted parameter
is re-estimated to force equality.

## Measurements and controls

Drive each clean and mutated workspace through its real `rule_mapping` → `pipeline`
stages. Compare complete keyed target rows, exact strings, in base features, sidecar,
SR02 selected forecasts, SR03 forecasts, every applicable tier feature/SR02/sidecar
output, and every raw/selected/market forecast file containing the targets. Require
nonempty target coverage in every declared stage and identical forecast-file inventory.
Target labels and outcome/stat rows are expected to differ. Hash/provenance receipts
may differ and are not forecast values.

The negative control runs a real sidecar stage under its `history` declaration, then
writes the target's future outcome into an existing numeric sidecar column. The same
comparison function must reject the clean/mutated stage pair. This demonstrates a
dataflow failure that the file-access declaration alone cannot detect. A boundary
control verifies strictly-after semantics and consistent archive/panel mutation.

This native T1 replaces none of the rejected archive T1 detector. It does not establish
general leakage freedom, independence of holdout custody, WTA tier support, full-bundle
T3 null behavior, or RB9 campaign acceptance. Results and measured runtime will be
recorded after execution below.
