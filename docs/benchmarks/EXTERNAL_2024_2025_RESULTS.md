# External matched comparisons, 2024–2025

These are retrospective, outcome-exposed comparisons on exact matched cohorts. They test the
frozen Alcaraz probabilities against two external probability sets; they are not prospective
evidence or reproductions of either external system's original headline result. Lower log loss and
Brier score are better; higher accuracy is better. The paired log-loss difference is **Alcaraz
minus external**, so a negative value favors Alcaraz.

The UTS comparison is extended to ATP 2025 and pooled 2024–2025, with the frozen model as the
comparator, as exposed retrospective data (EXT2025):
[UTS_INGRAM_2024_2025_RESULTS.md](UTS_INGRAM_2024_2025_RESULTS.md). The 2024 result on this page
stays the registered one.

## Headline results

| Cohort | Matches | System | Log loss | Brier | Accuracy |
|---|---:|---|---:|---:|---:|
| ATP 2024 full matched cohort | 2,681 | Alcaraz | **0.596486** | **0.206223** | **66.17%** |
| ATP 2024 full matched cohort | 2,681 | UTS fixed-formula adaptation | 0.620874 | 0.216443 | 64.60% |
| Four ATP 2025 clay events | 99 | Alcaraz | **0.633296** | **0.221066** | **62.63%** |
| Four ATP 2025 clay events | 99 | Published GNN probabilities | 0.720612 | 0.260066 | 52.53% |

| Paired comparison | Mean log-loss difference | Dependence-aware 95% interval | Resampling unit |
|---|---:|---:|---|
| Alcaraz minus UTS | **−0.024387** | [−0.031112, −0.017550] | 5,000 stationary calendar-week bootstrap draws, mean block 8 weeks |
| Alcaraz minus GNN | **−0.087317** | [−0.281213, −0.012128] | Exact 256 ordered resamples of the four event blocks |

For the 2,604 completed ATP 2024 matches, Alcaraz also had lower log loss than the UTS adaptation:
0.592442 versus 0.617796. The 4-week and 13-week UTS bootstrap sensitivities were also wholly
negative: [−0.031580, −0.017232] and [−0.030679, −0.018005].

The 2025 aggregate does not mean Alcaraz won every event. On the 23 Roland-Garros matches
(`2025-520`), Alcaraz log loss was **worse**: 0.709429 versus 0.693855 for the GNN, a paired mean
difference of +0.015575. The overall result was better because performance across the other event
blocks outweighed that loss.

| 2025 event ID | Matches | Alcaraz log loss | GNN log loss | Alcaraz minus GNN |
|---|---:|---:|---:|---:|
| `2025-0410` | 25 | 0.647067 | 0.728847 | −0.081781 |
| `2025-0416` | 43 | 0.596417 | 0.652998 | −0.056581 |
| `2025-1536` | 8 | 0.569598 | 1.135234 | −0.565635 |
| `2025-520` | 23 | 0.709429 | 0.693855 | +0.015575 |

## What was compared

**UTS adaptation.** This is a small implementation of the published [Ultimate Tennis Statistics /
Tennis Crystal Ball fixed formula](https://github.com/mcekovic/tennis-crystal-ball/tree/fcda1e607deb289369a0ce37d0f8c756b97910a6), using the four surface configurations frozen before 2024. It
replays public ATP history from 1968 onward and issues each probability at the accepted match-level
D−2 cutoff with native event-end result availability. The final repair consistently applies the
accepted identity contract to archive matches and rankings, including the global
`208597 → 209409` alias and one match-scoped correction. Pre-2024 backhand data are used only for
exact, unique name-to-ID matches; unmatched traits invoke the formula's native omission and weight
renormalization. This is a public-data formula adaptation, not the UTS website's historical output
or a reconstruction of its private database or reported headline metrics.

**Retained GNN probabilities.** The external side consists of 99 probabilities from the
[public TennisGNN repository](https://github.com/Faxulous/tennisgnn_predictions/tree/6676d7308c5dc4a320f99342d55b6640bf1028ed),
matched by event and player identity across four 2025 ATP clay events. GitHub verification
establishes commit existence before the reported match day, not necessarily historical
public visibility. The GNN's
internal feature and training cutoff remains opaque. The Alcaraz side was reconstructed
retrospectively at aligned target cutoffs from the unchanged checkpoint originally fit through
2023-12-30; it was not an issued 2025 forecast corpus. This comparison therefore does not reproduce
the GNN author's original headline experiment.

## Verification and bindings

An independent scalar recomputation from the frozen comparison rows reproduced match count, log
loss, Brier score, and accuracy for both systems in both comparisons. It also verified 2,681 unique
ATP 2024 IDs against the frozen membership, 99 unique GNN IDs against the strict comparator cohort,
binary labels, finite probabilities strictly between zero and one, the four GNN event counts, and
the report-to-commitment hash links. No fitting or model selection was run for this review.

| Artifact | UTS comparison SHA-256 | GNN comparison SHA-256 |
|---|---|---|
| Root forecast commitment | `1311e5180262ebba70d80fb5a99cf18f771dec074f7fccd8ea0e5bd40ffdee5a` | `2d46872fecbd4df198545027fccc1ccf4713dfb5ffb966184cc1853406c2606b` |
| Root matched report | `0e0797679db6501872d53391a916aff687942277882eaa48c15fb12c9398b468` | `e58dc2ccc0e05aa9c7790565af46ac39f492e1543b7fef462e50dd0562a75552` |
| Root review | `a8ac7488790b811484c396089d12f5b15b7698e4e682837afc9458b3f5317376` | `29abc66640879e07684152446016e12af43661e265cf9ed66847ba4fd7bb8efc` |
| Matched rows, retained privately | `3d987957712690b2a1fe00b89d93fc02f7676b1a6b7acf47be50e3a98aeadce0` | `337f4023fe4f8b0b292f068fd962d9ebf4521bbd4934d17b5631d44906c17835` |
| Committed probability file | `a9c10a9d681fdfee2a3584e3859beb68e048e41aacfaefca12775624f3944775` | `b21f6ee15acc0fb15f3069c6fff6e80c3cc1aa8224ae5642717ef04421889803` |

## Limits

- Both comparisons were selected and scored retrospectively after outcomes existed. They do not
  establish prospective validity, deployment performance, betting value, or causal superiority.
- The UTS comparison measures the specified fixed-formula public-data adaptation. Private database
  corrections, historical website output, and source-valid-time equivalence are not established.
- The GNN comparison has only 99 matches and four event clusters. Its event-block interval is
  descriptive and sensitive to individual events; the external model's internal cutoff is unknown.
- The incumbent and external systems do not have identical data pipelines. The figures answer the
  stated matched-cohort comparisons, not every possible controlled-information comparison.
- These results do not establish universal state of the art. The Roland-Garros slice is a concrete
  counterexample to any claim that Alcaraz was better on every included event.

Repository: `riddlejack/alcaraz`. This support artifact records results only; the published methods
are unchanged. Machine-readable aggregates and the same artifact bindings are in
`EXTERNAL_2024_2025_RESULTS.json`.
