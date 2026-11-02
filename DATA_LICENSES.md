# Data licences and redistribution

The package code is MIT-licensed under `LICENSE`. Source data is governed separately.
Permission to collect, permission to model, and permission to redistribute are different
questions; this repository follows the narrowest applicable boundary.

## Repository rule

The intended public boundary may contain code, source receipts and hashes, identity/event
mappings, aggregates, forecasts, scores, and synthetic acceptance fixtures. It is not
intended to contain raw provider files or row-level reproductions of a source.
Every published derived table must name its source and applicable terms.

## Sources

| Source | Governing record | Treatment in this repository |
|---|---|---|
| Jeff Sackmann, `tennis_atp` and `tennis_wta` | CC BY-NC-SA 4.0 | Consumed locally from the hash-pinned mirror named by `data/manifests/ARCHIVE01.json`, including the qualifying/Challenger and Futures files the current version's second model reads. The mirror is not redistributed. Any table carrying derived match, ranking, or player rows must use the same licence and attribution. |
| Jeff Sackmann, Match Charting Project | CC BY-NC-SA 4.0 | Used for limited corroboration in the archive, not as a current product-model input. Any future derived table must preserve attribution and the same licence. |
| Jeff Sackmann / Tennis Abstract player data | Purpose, non-commercial attribution, and no-betting limits; CC BY-NC-SA 4.0 treatment adopted by rebuild decision R16 | The collection remains outside this product repository and is not integrated into the accepted model runs. Raw responses are not tracked here. Any later derived table must carry the attribution block below and its collection dates. |
| tennis-data.co.uk annual results and odds workbooks | Provider/site terms; no redistribution right granted | Local input and descriptive market reference only. No odds, full result rows, or row-level derived reproduction is published. Event-name mapping metadata is permitted under the rebuild's R3 boundary. |
| Wikipedia draw and calendar pages | CC BY-SA 4.0 | Parsed locally for historical bridge rows. Small mapping tables may be tracked with source attribution; raw page captures are not copied into the product. |
| TennisMyLife yearly and ongoing files | The current site states MIT; the project adopted that statement under R23. An older retained README contains a conflicting non-commercial/no-redistribution statement | No TML raw or derived table is tracked or integrated today. If a qualified version is later published, retain source attribution, the version hash, the R23 terms decision, and the chronology/field conditions described in `docs/DATA.md`. |
| The Odds API and Software Heritage payloads | Provider-specific terms | Payloads stay local and are never tracked. |
| ATP/WTA official feeds and ITF | No automated-use authority established under the reviewed terms/bot boundary | Not collected or redistributed by this product. |

## Public attribution

> Data by [Jeff Sackmann / Tennis Abstract](https://github.com/JeffSackmann), licensed
> under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

The separate Tennis Abstract player-data collection is not part of the
accepted retrospective model runs described here.

When the first qualified Tennis Abstract-derived release is created, append the exact
collection start/end dates and source-version hashes to this block and to the product
README. Do not infer completion from a progress file.

## Current tracked data inventory

| Path | Contents | Redistribution basis |
|---|---|---|
| `data/sample/**`, `data/sample_tier/**` | Synthetic acceptance fixtures and expected results | MIT |
| `tests/live/**` | Synthetic manual workflow and adversarial controls | MIT |
| `tests/test_dynamics_numerical_repair.py` | Independently generated, seeded synthetic numerical regression; provenance in `tests/fixtures/README.md` | MIT |
| `data/mappings/wta_event_map/*.csv` | Event/edition and identifier mapping metadata; no odds or full result rows | R3 mapping boundary; Sackmann-derived columns under CC BY-NC-SA 4.0 |
| `data/manifests/**` | Hashes, receipts, bindings, and crosswalk metadata; not raw source payloads | Metadata only; underlying source terms still govern |
| `data/registries/**` | Project-generated experiment and score records | MIT, subject to cited source-result limits |

The archive files `td_row_date_defects.csv` and `winner_orientation_conflicts.csv` were
deliberately not copied because they reproduce tennis-data result rows. Other candidate
crosswalk and coverage files not required by the product trunk were also left out.

## Local live-workflow outputs

These are workspace outputs, not tracked redistributable datasets:

| Path | Provenance and treatment |
|---|---|
| `data/live/versions/*/results.csv` | Parsed English Wikipedia draw articles; retain article URL and revision attribution under CC BY-SA 4.0. Raw wikitext stays local. |
| `data/live/versions/*/serve_state.csv` | Tennis Abstract serve/return coverage; retain Jeff Sackmann / Tennis Abstract attribution and CC BY-NC-SA 4.0 treatment. |

## Attribution

Match, ranking, and player data © Jeff Sackmann, licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Wikipedia-derived
material remains subject to [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
