# Retained-input replay — September 16, 2026

Two new private snapshots passed independent source and numerical replay review using the existing product code and released checkpoints. They extend the earlier [D2 rehearsal](D2_READINESS.md). This is input integration and sensitivity evidence, not a newer fitted model, better measured accuracy, complete current data or prospective confirmation. Public example bindings and model defaults remain unchanged.

## Separately accepted increments

| Increment | Actual input change | Generated validation |
|---|---|---|
| Main-history serving fills | 751 existing matches; 13,518 formerly blank count cells; identities, outcomes and modeled dates unchanged | 18 fixtures across both tours, three surfaces and three history categories; 90 trained outputs and 36 Elo controls; 30 trained outputs independently reconstructed through native cores, with 510 exact comparisons; seven public-CLI forecasts in an isolated rehearsal ledger |
| Partial ATP tier extension | 7,676 results and 7,086 qualifying/Challenger count-feed rows on existing player-master IDs | Three full-tier fixture pairs; all six trained outputs independently reconstructed, with 102 exact comparisons; all base/main-dynamic/non-tier estimator values unchanged |

The serving tranche preserves 98,947 entirely unchanged history records. The tier tranche preserves the parent 697,193 results and 119,141 count rows, including their original availability bounds. Its V1 ordering attempt remains archived; V2 follows the existing native date/match-ID order without changing membership or source cells. Futures remain result/experience inputs only. One retired-match block retains only its valid service contest, with no imputation.

Temporal controls independently verify that future completion/publication/receipt or unresolved-overlap rows cannot change the earlier eligible panel or the trained forecast. Removing the controls exposes the poisoned native inputs. A changed history or tier binding cannot reuse the preceding input review receipt. No existing historical configuration or reserved-year guard was changed.

## Effects and interpretation

Thirty-two of 45 paired trained probabilities changed after the serving fills. Two of three full-tier probabilities changed after the tier extension. No outcomes were scored in these rehearsals: a changed probability is not a measured improvement.

An unchanged player's own history can still have changed serving features because the existing base model uses an eligible population prior. Independent weighted sums reproduce sampled prior-driven feature changes within 1.1e−15. Dynamic opponent/shared state can propagate changes as well. Added tier results can also alter opponents' ratings before their later main-tour interactions, affecting tier Elo without a direct addition for the fixture players. Controls therefore verify attributable changes and exact native reconstruction rather than blanket player-local invariance.

## Actual freshness

| Binding | ATP | WTA |
|---|---|---|
| Main-history modeled results | September 4, 2026 | August 1, 2026 |
| Main-history usable serving counts | September 1, 2026 | August 1, 2026 |
| Ranking edition | June 8, 2026 | June 8, 2026 |
| Tier modeled results/counts, second increment only | June 8, 2026; partial population | No active WTA tier route |
| Checkpoint target year | Accepted 2024 carry-forward | Accepted 2026 |

Whole-row availability temporarily withholds old results along with newly supplied counts: 739 fills qualify for a September 16 fixture at D−2; all 751 qualify for September 17 or later. The matrix used September 18 generated fixtures. Preserve the older snapshot for earlier cutoffs. Current receipts do not prove historical pre-match availability; the tier anchor+7 dates remain modeled-date proxies.

September ranking reports have separately improved identity mappings, including all top-100 players, but lack points and retain unresolved full-edition identities. They are not substituted for the June edition. This tier extension is also a partial current-master subset, not wholesale admission of overlapping annual and Tennis Abstract totals.

## Private evidence locators

The separate research archive stores the complete source-derived evidence under `work/ALCARAZ_NEXT_20260916/`; it is not a public data payload.

- Serving configuration: `serve_replay/candidate/private_live.json`; snapshot manifest SHA-256 `fd6155cdcb23a7695a939d10b7184bab5e49472f856c9635502a4027b0ca0e39`; independent final review `34c9e875cbce572607d2c89c6e7cf3aa73e7e2c681ff1a21e7e69ef76a8973bb`.
- Combined partial-tier configuration: `tier_replay/candidate/private_live.json`; snapshot manifest SHA-256 `2f2a7623b334b3437fd79e351ae5a0ce62331c3e834f1c12442e2113386d1796`; independent final review `721e8627438746675377b197c81e6264126ab4b405b008a9697f8aee63bd0e82`.
- Both configurations pass `tennislab readiness` with the accepted model bundle. The existing 53 live tests passed in the pinned environment. No durable product-code change was needed.

Set `TENNISLAB_WORKSPACE` to the parent containing the research archive and model bundle, then use an absolute private configuration path with the existing `readiness` or qualified-fixture workflow. Keep source-derived files private. These acceptances do not close all broader prospective integrity gates, promote a model, issue a real forecast or authorize publication.
