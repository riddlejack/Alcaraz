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
output, and every raw/selected/shared_base/market forecast file containing the targets. Require
nonempty target coverage in every declared stage and identical forecast-file inventory.
Market files cover exactly the targets with a nonmissing pre-match PS quote, identified
from the clean feature input; sports forecasts cover all chosen targets. The WTA base
world has two priced targets among the four chosen targets, and ATP tier has four.
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

## Local results (2026-09-14)

Design commit: `7e93a51`. Native comparisons ran after the B2 audit-log repair
`89de382`; the final validation-only cutoff guard `907b79e` is merged. The integrating
owner reran the complete integrated suite: 434 passed, one pre-existing optional
archive test skipped; all 12 native T1/comparator tests passed.

| Native path | Chosen targets | Mutated panel / lower-tier rows | Artifacts compared | Complete target rows compared |
|---|---:|---:|---:|---:|
| ATP tier, all five bundles, three SR02 variants | 4 | 531 / 490 | 30 | 120 |
| WTA base, both bundles, native WTA SR02 / sidecar | 4 (2 priced) | 531 / not implemented | 14 | 52 |

Every comparison is exact. All chosen target labels reverse. Every cutoff-date or
older panel row is unchanged. Every state stage produces changed later output when
the intervention legitimately becomes history, ruling out a no-op mutation. The
outcome-dependent sidecar control is rejected on both tours while its runtime
`history` declaration remains satisfied.

The four-chain verification took 232.48 seconds; the ATP clean/mutated pair took
168.93 seconds. Its first WTA comparison correctly exposed two unpriced targets that
were absent from market files. The final comparator now checks the exact pre-match
priced subset, rather than requiring quotes the fixture never contained. Root review
also added the `shared_base` forecast directory to the inventory. All eight final test
functions, including both real stage controls and the extended comparator, were then
executed successfully on the retained four runs. Normal collection is
`uv run pytest tests/test_native_t1.py`; lint and formatting pass for both new modules.

The native WTA fixture initially required three test-only schema corrections: no
skipped `bridge` stage when no bridge is configured, required WTA rule-contract
metadata, and the WTA ranking stream's fifth `tours` column. No production model,
frozen horizon, candidate setting, or original sample file was changed to obtain these
results. WTA tier support and full-bundle T3 remain separate open requirements.


## Integrated final check

The complete suite reran all four native chains with the final membership comparator
and four additional small negative controls. Exact comparison remains ATP 30 artifacts /
120 target rows and WTA 14 artifacts / 52 target rows. Final pair runtimes were 165.70 s
and 58.00 s, respectively; machine receipts are
`docs/equivalence/b2_review/native_atp.json` and `native_wta.json`.
The independent final comparator review is
`docs/equivalence/b2_review/native_t1_review.md`. RB9 campaign requirements remain open.
