# Lane E research-model companion release

Status: [published experimental companion](https://github.com/riddlejack/tennis-lab/releases/tag/campaign-e-research-models-2026-09-15),
verified by anonymous download on September 15, 2026. It does not replace the accepted
incumbent release. CI passed 621 tests with three expected skips at source commit
`4da58923024273e18219147047719d17759da5e7`; PR #1 merged the identical code tree.

Archive: 208,973,211 bytes. SHA-256:
`550ecb61ee9f5038ea0186b46e4e46582a8a1453a40a980b756d67d2a2f436d3`.

## Exact contents

`tools/build_campaign_model_release.py` accepts only the six fixed source inventories
recorded in [`CAMPAIGN_E_PUBLIC_INTEGRATION.md`](CAMPAIGN_E_PUBLIC_INTEGRATION.md):

- 140 byte-identical fitted estimators;
- 140 byte-identical source fit manifests; and
- 14 byte-identical target-fold decision records.

The copied source payload is exactly 294 files and 545,755,653 bytes. ATP covers raw
years 2014–2024 and target-fold decisions 2017–2024. WTA covers raw years 2016–2024 and
target-fold decisions 2019–2024. Every raw year has two HGB, three ridge, and two random-
forest estimators. The decisions retain both S2 candidate slopes, the selected S2 member
and slope, and all eight ordered S3 members and coefficients.

The builder rejects any extra or missing year/member, source-inventory digest drift,
model/fit-manifest mismatch, unexpected estimator type, feature-order drift, non-finite
decision parameter, private path, or row/workbook file type. It loads only these trusted,
hash-pinned project artifacts; it never loads an external competitor model.

## Verification and inference boundary

The existing release manifest receives optional `campaign_models` and
`campaign_decisions` indexes. `open_campaign_bundle` verifies the complete bundle before
any pickle load. `CampaignBundle.load_member` then rechecks the selected model and source
fit manifest immediately before deserialization and resolves a model only by
`(tour, raw_year, member_id)`. `CampaignBundle.load_decision` resolves the corresponding
S2/S3 parameters by `(tour, target_year)`.

All 140 objects must have the accepted `FittedProcedure` wrapper and expected scikit-learn
estimator type, exact ordered features, no identity vocabulary, no private/absolute path
string, no retained raw row/label/odds/winner field, and no matrix-like training payload.
Random-forest objects retain a uniform 0.5 augmentation-weight vector; it contains no row
values, keys, or labels and is preserved to keep the fitted estimator byte-identical.

The build and standalone verifier run every estimator on a nonzero artificial prepared
row and its reflected orientation, requiring distinct probabilities that complement
within `1e-14`. They also apply every saved decision to artificial eight-member
probabilities. These checks test the interface and saved parameters, not historical or
future performance.

Exact numerical inference still needs a feature row constructed in the selected fit
manifest's order from the applicable chronological Elo, serve/return, ranking, workload,
trait, dynamic, and ATP tier state. S2 then needs the selected RF probability and saved
slope; S3 needs all eight ordered raw-member probabilities, including separately
constructed result Elo. The bundle deliberately excludes that current or historical
row-level state. It is a research-model collection, not a player-name application.

## Build and verify

Use the frozen accepted consumer workspace only as the source:

```sh
uv run python tools/build_campaign_model_release.py \
  --source "/path/to/accepted-d93-d94-consumer" \
  --output "/path/to/tennislab-campaign-e-research-models-2026-09-15" \
  --tar "/path/to/tennislab-campaign-e-research-models-2026-09-15.tar.gz"
```

Verify an unpacked bundle without the source workspace:

```sh
uv run python tools/build_campaign_model_release.py \
  --verify "/path/to/tennislab-campaign-e-research-models-2026-09-15"
```

The build creates the archive twice and requires byte equality. Before loading a public
asset, authenticate its published tarball SHA-256 through the release page; a replacement
manifest cannot authenticate itself.

## Scientific and license status

The artifact labels are `research`, `retrospective outcome-exposed`, `experimental`,
`no nomination`, `not a default`, and `not prospective evidence`. The accepted result is
negative/inconclusive, and the incumbent remains the default.

MIT applies to the loader code. The learned artifacts use the same conservative
CC BY-NC-SA 4.0 package treatment as the accepted incumbent bundle. The included notice
credits Jeff Sackmann's ATP/WTA datasets and records the tennis-data.co.uk and Wikipedia
input roles without copying their workbooks, pages, odds, or rows. Underlying database
terms remain separate; this package does not relicense them.

