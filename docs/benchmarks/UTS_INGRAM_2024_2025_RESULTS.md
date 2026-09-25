# Ultimate Tennis Statistics and Ingram, ATP 2024–2025 (EXT2025)

> **2025 is exposed retrospective data, not a holdout.** It was inspected before the model
> freeze (archive decision D134) and scored by REFIT2025 (D137, D138). The accepted results
> remain the registered claims, and each extended number is shown beside its registered
> one: [EXTERNAL_2024_2025_RESULTS.md](EXTERNAL_2024_2025_RESULTS.md) for Ultimate Tennis Statistics and [INGRAM_2024_RESULTS.md](INGRAM_2024_RESULTS.md) for Ingram, both ATP 2024.
> Accepted as archive decision D139, independently reconstructed (Ultimate Tennis Statistics:
> verdict ACCEPT; Ingram: verdicts ACCEPT for the scoring and
> ACCEPT for the continued 2025 fit).

Both external systems are scored with one scorer on one match set per block: ATP 2024,
ATP 2025 and the two pooled (design amendments A2, A4 and A5). The primary comparator is the
frozen model (ATP `full_tier_entry`, D134); the continuity comparator is the version the
accepted 2024 rows used (`full_tier`). Every number is filled from
[uts_ingram_2024_2025.json](uts_ingram_2024_2025.json) and the accepted JSONs.

## Ultimate Tennis Statistics fixed formula

A public-data adaptation of the published formula, not the website's own output (see the
accepted page for the adaptation).

### Frozen model (primary)

| Block | Matches | Alcaraz | UTS | Alcaraz − UTS | 95% interval, eight-week blocks |
|---|---:|---:|---:|---:|---:|
| 2024 | 2,681 | 0.5956 | 0.6209 | −0.0253 | [−0.0326, −0.0176] |
| 2025 | 2,589 | 0.6103 | 0.6345 | −0.0242 | [−0.0344, −0.0157] |
| 2024–2025 pooled | 5,270 | 0.6028 | 0.6276 | −0.0248 | [−0.0309, −0.0191] |

### Accepted version (continuity)

| Block | Matches | Alcaraz | UTS | Alcaraz − UTS | 95% interval, eight-week blocks |
|---|---:|---:|---:|---:|---:|
| 2024 | 2,681 | 0.5965 | 0.6209 | −0.0244 | [−0.0311, −0.0176] |
| 2025 | 2,589 | 0.6122 | 0.6345 | −0.0224 | [−0.0308, −0.0150] |
| 2024–2025 pooled | 5,270 | 0.6042 | 0.6276 | −0.0234 | [−0.0286, −0.0184] |

The continuity 2024 row equals the registered 2024 result value for value (the builder
checks it): −0.0244
[−0.0311, −0.0176] on 2,681 matches.
UTS is not run on 2017–2023: those seasons lie in the formula's weight-tuning window,
predate its code or would need a new timing exclusion (design amendment A2).

## Ingram's Bayesian point model

The unchanged paper model, fitted for 2025 with the accepted settings and the 2024 seeds;
its raw posterior forecast is scored.

### Frozen model (primary)

| Block | Matches | Alcaraz | Ingram | Alcaraz − Ingram | 95% interval, eight-week blocks |
|---|---:|---:|---:|---:|---:|
| 2024 | 2,681 | 0.5956 | 0.6417 | −0.0461 | [−0.0582, −0.0349] |
| 2025 | 2,589 | 0.6103 | 0.6526 | −0.0423 | [−0.0534, −0.0323] |
| 2024–2025 pooled | 5,270 | 0.6028 | 0.6471 | −0.0443 | [−0.0519, −0.0367] |

### Accepted version (continuity)

| Block | Matches | Alcaraz | Ingram | Alcaraz − Ingram | 95% interval, eight-week blocks |
|---|---:|---:|---:|---:|---:|
| 2024 | 2,681 | 0.5965 | 0.6417 | −0.0452 | [−0.0568, −0.0347] |
| 2025 | 2,589 | 0.6122 | 0.6526 | −0.0404 | [−0.0496, −0.0319] |
| 2024–2025 pooled | 5,270 | 0.6042 | 0.6471 | −0.0429 | [−0.0497, −0.0359] |

The continuity 2024 log losses equal the registered 2024 result (the builder checks them).
The registered interval, −0.0452
[−0.0565, −0.0350] on 2,681 matches, came from
the Ingram run's own bootstrap; the intervals here come from this page's common scorer, so the
2024 interval differs slightly while the points agree.

**How the 2025 fit ran.** The first attempt finished sampling and passed the frozen gates in
every period, then stopped in the prediction step on one match-probability draw that floating-point
rounding had put a hair above one. The second attempt continued from the saved samples with the
frozen seeds, clipping probabilities within 1e-12 of the boundary and
recording each clip: three clips in all, all in best-of-five matches
according to design amendment A5, which names them. The
three periods without a clip that were
checked before the freeze reproduced their forecasts byte for byte from the saved samples.
Model, sampler, seeds, gates, inputs and scoring are unchanged.

## Limits

- A public-data formula adaptation, not the UTS website's historical output or its private
  database.
- No claim of prospective validity, betting value or universal state of the art.
- The 2024–2025 blocks share 2024 with the registered result and are not an independent
  confirmation.
