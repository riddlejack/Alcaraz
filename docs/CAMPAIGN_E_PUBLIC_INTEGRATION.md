# Lane E public integration

Status: complete. Reviewed source `4da58923024273e18219147047719d17759da5e7`
passed GitHub CI (621 passed, three expected skips, lint and both reproductions),
merged through [PR #1](https://github.com/riddlejack/tennis-lab/pull/1), and its
[experimental companion](https://github.com/riddlejack/tennis-lab/releases/tag/campaign-e-research-models-2026-09-15)
passed anonymous-download checksum verification. The accepted aggregates do not
nominate a model or change the public default.

## Integration boundary

This branch starts from public `main` at `fb96edf`. It integrates the reviewed Lane E
campaign mechanics through EC-01 successor `644a57d` while preserving the accepted
model release, Lane G benchmark, live workflow, and CI repairs already on public main.

The included public surface is deliberately smaller than the execution workspaces:

- `tennislab.campaign` implements the manifest-bound forecast, barrier, report, and
  verification graph for S0-S3;
- the existing CLI gains `tennislab campaign` without removing live, benchmark, chain,
  report, or reproduction commands;
- SR03 can commit complete fit records while deferring objective values until the
  campaign barrier has been verified;
- the numerical adapter and feature contract support the two fixed random-forest
  candidates without changing the historical default learner menu;
- synthetic end-to-end, stack, EC-01 custody, SR03 disclosure, planted-integrity, and
  repository-hygiene tests exercise the public contracts;
- the obsolete `fit_missing_rf` helper name is an immediate no-I/O refusal. Fitting is
  available only through the reviewed, manifest-bound campaign graph.

Not imported: producer and consumer workspaces, real source workbooks, labels, feature
rows, training keys, row predictions, private configs or authorizations, local evidence
indexes, execution controllers, native run trees, or machine-specific paths. Those
artifacts remain outside Git and unchanged.

## Verification so far

The focused public-integration command passed 104 tests with two deliberate skips. The
skips require a separately supplied, test-only copy of the frozen EC-01 graph; the
remaining EC-01 tests use synthetic temporary graphs and pass. The final repository-wide
`make check` also passed: lint and format checks were clean, 618 tests passed with three
known skips, and both committed small synthetic reproductions passed.

## Accepted bounded result

Independent review accepted the exact D93/D94 historical consumer result and reproduced
all 4,000 bootstrap replicates, 28 S2/S3 criterion commitments, 42 selection memberships,
and 127,488 target probabilities with separate arithmetic. The review is
`LANE_E_D93_D94_RESULT_REVIEW.md`, SHA-256
`4e872a983d79721d3262924b0367c655c2d290c44608ddcf10fae84f7b9d8119`.

ATP S3 minus S0 equal-year log loss is `-0.0004187360339825443` over 18,972 matches;
its conditional interval crosses zero. WTA is `0.0006742605931336596` over 12,900
matches and favors S0. Neither tour meets the registered nomination screen. S1 and S2
underperform S0 on both tours, so the incumbent remains the default and no model is
promoted. The exact grains, secondary results, market comparison, preserved D93 failure,
D94 retry, and limitations are in [`CAMPAIGN_E_RESULTS.md`](CAMPAIGN_E_RESULTS.md).

## Research-artifact inventory

This fixed inventory is implemented by `tools/build_campaign_model_release.py` as a
deterministic companion outside Git, now published as a separate experimental release. The
incumbent `models-2026-09-14` release remains unchanged and separate. Build, loader,
audit, inference, required-state, and license details are in
[`CAMPAIGN_E_MODEL_RELEASE.md`](CAMPAIGN_E_MODEL_RELEASE.md).

The candidate payload copies only byte-identical fitted estimators, their existing
fit manifests, and the pre-barrier decision records that contain learned S2 slopes,
candidate selection, and S3 coefficients. It retains every raw numerical member, not
only the selected or nonzero members.

The unchanged incumbent release remains the supported default package. This larger
companion inventory represents the evaluated campaign research graph: it includes the
incumbent-compatible HGB raw members alongside the newly evaluated ridge/RF members and
their fold-specific combination parameters, without designating any replacement.

| Payload class | ATP | WTA | Total |
|---|---:|---:|---:|
| `model.joblib` | 77 files, 297,059,106 bytes | 63 files, 247,372,310 bytes | 140 files, 544,431,416 bytes |
| `fit_manifest.json` | 77 files, 696,336 bytes | 63 files, 536,237 bytes | 140 files, 1,232,573 bytes |
| target-fold decision JSON | 8 files, 52,397 bytes | 6 files, 39,267 bytes | 14 files, 91,664 bytes |
| **Exact copied payload** | **162 files, 297,807,839 bytes** | **132 files, 247,947,814 bytes** | **294 files, 545,755,653 bytes** |

ATP raw-year coverage is 2014-2024; WTA raw-year coverage is 2016-2024. Each raw year
contains the same seven fitted members:

| Member | ATP files / bytes | WTA files / bytes |
|---|---:|---:|
| `hgb_leaf07_depth3` | 11 / 2,562,402 | 9 / 1,975,302 |
| `hgb_leaf15_depth4` | 11 / 3,936,978 | 9 / 3,016,342 |
| `ridge_c001` | 11 / 235,884 | 9 / 192,996 |
| `ridge_c01` | 11 / 235,884 | 9 / 192,996 |
| `ridge_c1` | 11 / 235,884 | 9 / 192,996 |
| `rf_leaf50` | 11 / 191,586,757 | 9 / 160,220,599 |
| `rf_leaf100` | 11 / 98,265,317 | 9 / 81,581,079 |

The inventory digests below hash sorted lines of
`relative_path<TAB>bytes<TAB>sha256<LF>`. They identify the reviewed source set without
placing any payload in Git.

| Inventory | SHA-256 |
|---|---|
| ATP models | `26dc5ebb6cfdb0f761d19df95691c52f1cb89940ba8678ff6f0b357bd0d7196b` |
| ATP fit manifests | `5857024a03476a80a9fad85fdf94883841f5010316ee541b1d678569fa28b3f9` |
| ATP decisions | `cb3391f683ca52f89e300f9bf947053271c1651654de7db5f412c870bfd7a198` |
| WTA models | `718e7ab714d02c5d630e2227e74757d5b607d484b55f00b9a5e7febcf4a4067d` |
| WTA fit manifests | `fcbdb9507e7b7f94a858ac33aa754635cde4df65a39d9677ae36e221ba4ecffa` |
| WTA decisions | `84816e6d44b41f4814d108f4b47300eed6015d2ad3dc8bb6cf029e5f1e516a04` |

The decision records cover ATP target years 2017-2024 and WTA target years 2019-2024.
For each fold they retain both RF candidate slopes and the selected S2 candidate/slope,
plus the eight-member S3 order, eight coefficients, optimizer diagnostics, and criterion
commitments. S1 has no learned parameter: it is the fixed equal-probability blend of S0
and result Elo.

## Inference and data boundary

The fitted objects require CPython 3.14.6, NumPy 2.5.3, SciPy 1.18.1,
scikit-learn 1.9.1, and joblib 1.6.0. The existing `FittedProcedure` supports the HGB,
ridge, and RF object types, but the current public release manifest/loader addresses an
incumbent checkpoint by tour, rung, and target year. A companion release therefore
needs a reviewed schema extension keyed by tour, raw year, and member ID; it must verify
the complete bundle before any pickle load.

Weights and combination parameters are not a player-name forecasting application.
Exact inference also requires a constructed feature row in the fit manifest's order;
the applicable S2 fold decision; all eight S3 member probabilities; and the chronological
feature, identity, ranking, workload, result-Elo, tier-state, and D-2 cutoff producers.
Those raw inputs and row-level states are intentionally excluded. The incumbent pooled
Elo snapshot is a separate current aggregate state and is not a substitute for the
historical fold-specific result-Elo and feature state used by this campaign.

Training-key files, labels, feature matrices, prediction CSVs, source workbooks, odds,
and private custody documents stay out of both Git and the proposed artifact bundle.
Their hashes may be referenced by the retained fit manifests; the underlying rows are
not redistributed.

## Publication verification

All publication steps completed on September 15, 2026: independent scientific result
acceptance; root integration review; deterministic packaging and all-object checks;
exact-commit GitHub CI; merge; separate experimental release; and anonymous download.
The public tarball is 208,973,211 bytes with SHA-256
`550ecb61ee9f5038ea0186b46e4e46582a8a1453a40a980b756d67d2a2f436d3`.
Root independently verified all 302 archive files and the merge's tree equality to the
CI-tested source commit. The incumbent release and default remain unchanged.
