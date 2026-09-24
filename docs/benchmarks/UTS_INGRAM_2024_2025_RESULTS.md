# Ultimate Tennis Statistics and Ingram, ATP 2024–2025 (EXT2025)

> **2025 is exposed retrospective data, not a holdout.** It was inspected before the model
> freeze (archive decision D134) and scored by REFIT2025 (D137, D138). The accepted results
> remain the registered claims, and each extended number is shown beside its registered
> one: [EXTERNAL_2024_2025_RESULTS.md](EXTERNAL_2024_2025_RESULTS.md) for Ultimate Tennis Statistics and [INGRAM_2024_RESULTS.md](INGRAM_2024_RESULTS.md) for Ingram, both ATP 2024.
> The extension's acceptance is pending a decision entry.

Both external systems are scored with one scorer on one match set per block: ATP 2024,
ATP 2025 and the two pooled (design amendments A2 and A4). The primary comparator is the
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

The 2025 Ingram fit and its scoring pass with the same scorer are pending (design
amendment A4); until they exist the registered 2024 result stands alone:
−0.0452
[−0.0565, −0.0350] on 2,681
matches (its own bootstrap), against `full_tier`.


## Limits

- A public-data formula adaptation, not the UTS website's historical output or its private
  database.
- No claim of prospective validity, betting value or universal state of the art.
- The 2024–2025 blocks share 2024 with the registered result and are not an independent
  confirmation.
