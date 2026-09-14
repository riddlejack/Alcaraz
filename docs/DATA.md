# Data: what exists, what qualified, what the model used

Acquisition, qualification, and model integration are separate events. A downloaded file
is not automatically usable; a qualified source is not automatically part of a run; and
a repository dated 2026-09-14 does not imply that its models consumed every result through
that date.

## Actual model horizons

| Accepted retrospective run | Source use | Configured horizon | Target/evaluation horizon |
|---|---|---|---|
| ATP TIER01 attempt 002 | Hash-pinned Sackmann mirror and local tennis-data annual workbooks, with a 2024 Wikipedia bridge; lower-tier history for `full_tier` | Tour panel 2005–2024; feature history floor 2011; rankings from 2000 | 2017–2024; 18,972 all targets, 18,882 matched priced targets |
| WTA02 attempt 002 | Hash-pinned Sackmann mirror, 2025–2026 tennis-data workbooks, and 2026 Wikipedia bridge files | Panel 2007–2026; feature history floor 2011; serve-count history from 2016; rankings from 2000 | 2025–2026; 4,296 all targets, 2,344 matched priced targets |

The exact configurations are `configs/chains/atp_tier01_2017_2024.json` and
`configs/chains/wta02_2025_2026.json`; generated target counts are in
`docs/ladder.json` and the accepted run reports. The WTA end year means “the versioned
files bound by that run,” not complete coverage through 2026-09-14. Its 2025–2026 target
window is exposed development data and carries known date/overlap defects.

Sports rungs do not use price as a predictor, but their historical population is
market-source-aligned. WTA preparation iterates matched market rows; ATP begins from
market/common-panel candidates. The current results therefore do not establish
performance on the broader universe of public result rows.

## Source status matrix

| Source | Acquired or observed | Qualification | Integrated into accepted retrospective runs |
|---|---|---|---|
| Jeff Sackmann archive mirror (`tennis_atp`, `tennis_wta`, rankings, players) | Frozen tar and manifest hashes retained in the research archive | Primary historical source with per-field limitations | Yes, both tours, within the horizons above |
| tennis-data.co.uk annual workbooks | Versioned local workbooks and hashes | Results/date fields used under recorded semantics; prices are closing-like with unknown quote time; no redistribution right | Yes, as a local join and market reference; ATP 2017–2024 and WTA 2025–2026 scored on matched priced cohorts |
| Wikipedia draw/calendar pages | Receipted parsed bridge files, including 2024 ATP and 2026 WTA paths bound by the configs | Results-only; dates are event anchors or completion bounds, not match clocks | Yes, in the historical bridge paths; those weaknesses limit chronology claims |
| Match Charting Project | Retained charting evidence | Charter-asserted dates and partial serve counts; selective coverage | Corroboration/audit only, not a model trunk source |
| Tennis Abstract player data | Owner-permitted acquisition over a 5,683-player inventory; resumed after the retained WTA parse failure and offline repair described below | `PERM-TA-002` supplements `PERM-TA-001`; integer two-sided serve counts observed; payload dates are event anchors; WTA depth is version-dependent; output still requires final qualification | No. Progress counts are not qualified-player counts and no accepted run uses the collection |
| TennisMyLife yearly and ongoing files | Owner-downloaded 172-file zip plus retained read-only comparisons | Results/count roles qualified with conditions; source versioning, anomaly quarantine, and cross-source count rules required. Date admissibility is open because retained comparisons include early as well as late offsets | No. Neither accepted run nor a release snapshot uses TML |
| ATP/WTA official feeds and ITF | Limited read-only probes | Automated access not authorised under the reviewed terms/bot boundary | No |

## Date evidence is not one column

A pre-match feature can use a result only when its availability is admissible at the
declared cutoff. The data model therefore distinguishes:

- event anchor;
- match or completion bound;
- source publication time, when known;
- local receipt time; and
- forecast issue time.

The Tennis Abstract payload's date is an event anchor, not a match date. TennisMyLife's
2026 ATP date comparisons are mostly same-day or later than the comparison source, but
not universally so. Retained evidence includes:

| Comparison file | Population | TML date minus comparison date |
|---|---:|---|
| `acquisition/tml_zip/date_offsets.csv` | 1,538 nonblank set-B offsets | −1 day: 2; 0: 1,332; +1: 203; +2: 1 |
| `acquisition/tml/crosscheck_tachart.csv` | 132 matched men's-tour rows | −59: 1; −2: 1; −1: 4; 0: 100; +1: 25; +2: 1 |

These are disagreements, not automatic proof that either source is ground truth. They do
invalidate the stronger inherited statement that a TML date is always a safe availability
upper bound. D2 must quarantine unresolved chronology until the concrete cases and an
admissibility rule are independently reviewed.

## Coverage that shaped the features

The archive's generated coverage matrix reports the raw historical source inventory,
not the rows used by one model:

| Archive inventory, 2000–2024 unless noted | Rows | Complete usable serve block |
|---|---:|---:|
| ATP singles across investigated families | 644,990 | 28.6% |
| WTA singles across investigated families | 530,860 | 7.8% |

The WTA inventory also contains 30,320 partial rows. Independent reconstruction corrected
one important sub-count: 26,618 WTA rows from 2003–2015 are missing exactly `SvGms`, not
26,687. Those gaps are why the accepted WTA configuration begins serve-count history in
2016. Men's Futures and much early Challenger/qualifying history lack the same blocks.

Sources: archive `acquisition/COVERAGE_SUMMARY.md`, generated
`acquisition/coverage_matrix.csv`, and `LANE_A_reconstruction_result.md`. “No source
qualified among those investigated” is narrower than “the data does not exist.”

## Tennis Abstract collection boundary

The site owner first authorised purpose-bounded retrieval with attribution under
`PERM-TA-001`. `PERM-TA-002` supplements that record by allowing adaptive request
frequency provided traffic does not slow or crash the site. It does not change the
purpose, non-commercial attribution, or no-betting boundaries. The collector voluntarily
retains one connection and an identifying user agent.

Bounded tests reached HTTP 429 at 1.0–1.25 seconds and again during the longer 2.0–2.5
second follow-up. The selected tested-clean tier is therefore 3.0–3.5 seconds, with the
slower-tier and stop/escalation rules recorded in the monitor runbook. This is an
operating choice, not a new fixed permission ceiling.

At the dated 2026-09-14T22:42Z snapshot, collection had been paused since 22:20Z on a
retained 39-field WTA parse failure: 1,326 players were complete, 20 were
evidence-bearing unavailable, 1,346 of 5,683 were terminal, and 337,419 rows had been
parsed. Offline parser diagnosis was underway at that snapshot. These are acquisition
counts, not evidence that the player set is complete, source-qualified, or integrated.
An offline review subsequently verified that the source renderer fills five omitted
trailing metadata fields with blanks. The collector resumed at the same 3.0–3.5 second
tier at 2026-09-14T22:51:45Z, with a healthy monitor reported at 22:52:26Z. The earlier failure and
receipts remain retained. No accepted model run ingests this collection.

## Release snapshot status

There is no accepted “data through 2026-09-14” product snapshot today. The first manual
update/forecast/score slice and two subsequent repairs were rejected under independent
reconstruction. The targeted repair at `5089b24` is now independently accepted on
synthetic controls, with Elo issuance only (see [live workflow](live/README.md)). This
does not itself perform D2, which must:

1. bind exact receipted source versions and fixture identity;
2. apply per-field qualification and date admissibility;
3. produce both tours in the existing corrected schema;
4. connect the existing fitted artifacts without refitting; and
5. pass independent reconstruction before a real batch is issued.

Until then, 2026-09-14 is a code/review date. The accepted model horizons are the two
explicit configurations at the top of this page.

## Redistribution rule

The intended public product boundary carries code, manifests and hashes, mapping/alias
tables, aggregates, forecasts, scores, and synthetic acceptance fixtures. A publication
audit identified a real-input numerical fixture, now replaced by an independently
generated synthetic regression. The owner approved retaining exactly that historical
file under a documented one-file exception on 2026-09-14; no history rewrite is planned.
The exception does not authorize publishing other archive data. Odds-provider rows
and payloads governed by local or provider-specific terms remain outside Git.
`DATA_LICENSES.md` records the current inventory and historical fixture provenance.
