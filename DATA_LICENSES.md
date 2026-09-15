# Data licences and redistribution

The package code is MIT-licensed under `LICENSE`. Source data is governed separately.
Permission to collect, permission to model, and permission to redistribute are different
questions; this repository follows the narrowest applicable boundary.

## Repository rule

The intended public boundary may contain code, source receipts and hashes, identity/event
mappings, aggregates, forecasts, scores, and synthetic acceptance fixtures. It is not
intended to contain raw provider files or row-level reproductions of a source. A former
real-input regression fixture has been replaced with a synthetic case; its copy in Git
history is retained under the owner-approved one-file exception documented below.
Every published derived table must name its source and applicable terms.

## Sources

| Source | Governing record | Treatment in this repository |
|---|---|---|
| Jeff Sackmann, `tennis_atp` and `tennis_wta` | CC BY-NC-SA 4.0 | Consumed locally from the hash-pinned mirror named by `data/manifests/ARCHIVE01.json`. The mirror is not redistributed. Any table carrying derived match, ranking, or player rows must use the same licence and attribution. |
| Jeff Sackmann, Match Charting Project | CC BY-NC-SA 4.0 | Used for limited corroboration in the archive, not as a current product-model input. Any future derived table must preserve attribution and the same licence. |
| Jeff Sackmann / Tennis Abstract player data | Owner permission record `PERM-TA-001`, supplemented by adaptive-pacing record `PERM-TA-002`; purpose, non-commercial attribution, and no-betting limits unchanged; CC BY-NC-SA 4.0 treatment adopted by rebuild decision R16 | The permitted collection remains outside this product repository and is not integrated into the accepted model runs. Raw responses are not tracked here. Any later derived table must carry the attribution block below and its collection dates. |
| tennis-data.co.uk annual results and odds workbooks | Provider/site terms; no redistribution right granted | Local input and descriptive market reference only. No odds, full result rows, or row-level derived reproduction is published. Event-name mapping metadata is permitted under the rebuild's R3 boundary. |
| Wikipedia draw and calendar pages | CC BY-SA 4.0 | Parsed locally for historical bridge rows. Small mapping tables may be tracked with source attribution; raw page captures are not copied into the product. |
| TennisMyLife yearly and ongoing files | The current site states MIT; the owner adopted that statement under R23. An older retained README contains a conflicting non-commercial/no-redistribution statement | No TML raw or derived table is tracked or integrated today. If a qualified version is later published, retain source attribution, the version hash, the R23 terms decision, and the chronology/field conditions described in `docs/DATA.md`. |
| The Odds API and Software Heritage payloads | Provider-specific terms | Payloads stay local and are never tracked. |
| ATP/WTA official feeds and ITF | No automated-use authority established under the reviewed terms/bot boundary | Not collected or redistributed by this product. |

## Public attribution

> Data by [Jeff Sackmann / Tennis Abstract](https://github.com/JeffSackmann), licensed
> under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

The internal permission identifiers and collection limits remain in the technical source
table above. The separate Tennis Abstract player-data collection is not part of the
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

Earlier commits contain `tests/fixtures/solver_precision_2005-06-25.json`, a real
11-match numerical regression capture derived from Jeff Sackmann's historical data via
the hash-pinned `ARCHIVE01` mirror. Its source-data attribution and CC BY-NC-SA 4.0
treatment apply separately from the MIT code license. The current test generates an
independent artificial case and preserves the original numerical failure check.

On 2026-09-14 the owner approved preserving Git history with a one-file exception to
the project's no-source-row rule. The exception covers only the historical
`tests/fixtures/solver_precision_2005-06-25.json` introduced at
`f66f953acd6b3cf123bf528480f20810a9e65b66`: 20,755 bytes, 11 matches and 69 numerical
states; SHA-256 `06f690d8e7318790c273b57e2d4eff5fe2f2f89da2f07c637203ec41e0700814`.
It does not authorize restoring the file to the current tree or publishing other archive
rows. Preserve Jeff Sackmann attribution and CC BY-NC-SA 4.0 terms for this historical
data; MIT applies separately to code. The audit found a project-policy inconsistency,
not legal infringement. This decision resolves that inconsistency without rewriting
commit history.

## Local live-workflow outputs

These are workspace outputs, not tracked redistributable datasets:

| Path | Provenance and treatment |
|---|---|
| `data/live/versions/*/results.csv` | Parsed English Wikipedia draw articles; retain article URL and revision attribution under CC BY-SA 4.0. Raw wikitext stays local. |
| `data/live/versions/*/serve_state.csv` | Tennis Abstract serve/return coverage; retain Jeff Sackmann / Tennis Abstract attribution, PERM-TA-001 as supplemented by PERM-TA-002, and CC BY-NC-SA 4.0 treatment. |

## Attribution

Match, ranking, and player data © Jeff Sackmann, licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Wikipedia-derived
material remains subject to [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
