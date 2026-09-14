# Live update, prospective fixtures and the prospective ledger (Lane D)

Status: **design frozen before the first rehearsal run; no campaign is authorised by this
document.** Historical chains, frozen configs and the equivalence oracle are untouched
(RB10). Everything here lives under `src/tennislab/live/`, `configs/live/` and the
workspace directory `data/live/`. Decisions cited: archive R6, R12–R14, R17, R19–R22;
product RB10, RB13.

## 1. What is delivered

1. `tennislab update` — an explicit, user-invoked, versioned refresh. No scheduler, no
   liveness probes (R14 disables UPDATE_SPEC's automatic tennis-data probe).
2. `tennislab fixture` — a prospective fixture constructor: neutral player-A/player-B rows
   with no outcome, no target score and no target-match statistic.
3. `tennislab forecast` — issues forecasts for qualified fixtures through the declared
   rungs and appends them to an append-only, hash-chained ledger.
4. `tennislab ledger` — verify the chain, record start/result/proof events, show state.
5. `tennislab settle` — evaluation after the barrier; the only writer of a score.

## 2. Workspace layout (RB10: separate from every historical run)

```
data/live/
  sources/<source_id>/attempts/<attempt_id>/receipt.json   one immutable dir per attempt
  sources/<source_id>/attempts/<attempt_id>/raw/…          retained bytes, never rewritten
  sources/<source_id>/latest.json                          advanced atomically after validation
  versions/<version_id>/results.csv                        normalized results (§4)
  versions/<version_id>/serve_state.csv                    per-player last usable serve block
  versions/<version_id>/rankings.csv                       last-known ranking per player
  versions/<version_id>/quarantine/{identity,duplicates,conflicts,unresolved}.csv
  versions/<version_id>/{diff.json,completeness.json,manifest.json}
  versions/latest.json
  fixtures/<batch_id>/{fixtures.jsonl,forecasts.jsonl,manifest.json}
  ledger/ledger.jsonl                                      append-only, hash-chained (§6)
  proofs/<record_sha256>.request.json | .attestation.json
  settlement/<settlement_id>/{scores.csv,coverage.csv,manifest.json}
```

`attempt_id` and `version_id` are `<UTC stamp>-<8 hex of content hash>`; a retry never
reuses a directory, and an interrupted attempt (`status != "complete"`) can never be
named by `latest.json`. Wall clocks appear only in receipts, manifests and ledger records,
never inside `results.csv`, `serve_state.csv` or `rankings.csv`.

## 3. Sources (one interface, per-field qualification)

| Source id | Kind | Status in `configs/live/live.json` | Supplies | Never supplies |
|---|---|---|---|---|
| `wikipedia_results` | Wikimedia core REST (`api.wikimedia.org/core/v1/wikipedia/en/page/<title>`), wikitext + revision id + revision timestamp | `qualified` for results only (R12) | winner, score, round, status, seed/entry, source revision, publication upper bound | match date, serve counts, rankings, minutes |
| `tennisabstract_serve` | parsed CSV feed in the TAPLAYER01 layout (`date_basis = event_anchor`) | `qualified_serve_state` under `PERM-TA-001` (R16, R20) | per-player serve/return counts for both sides, per-field coverage | a match date, a D−1 clock |
| `rankings_feed` | Sackmann-layout weekly ranking file | `qualified_last_known` | rank/points with `ranking_date` as publication date | anything after its last list |
| `tennismylife` | parsed CSV feed behind the same interface | `candidate_not_qualified` (R22) | refused until a qualification record names the fields | — |
| `wta_official`, `atp_official`, `tennis_data` | — | `blocked_terms` / `unreachable` (R14) | never requested | — |

A source is used for a field only when its config status qualifies that field; the CLI
refuses otherwise and says which record is missing. `en.wikipedia.org/w/` is never
requested (robots disallow). Requests are serial with a minimum spacing and an honest
user agent. Network is optional everywhere: every command accepts `--replay <dir>` and
rehearses against retained or synthetic responses through the same code path.

## 4. Normalized results row (`results.csv`)

Stable identity `row_id = sha256(tour, event_id, round, player_a_id, player_b_id)` with
`player_a_id < player_b_id` (neutral orientation). Fields: `tour, event_id, event_name,
level, surface, round, player_a_id, player_b_id, player_a_name, player_b_name,
winner_side (a|b|""), score, sets, status (completed|retired|walkover|default|pending),
target_anchor_date, completion_upper_bound, completion_basis, publication_upper_bound_utc,
source_id, source_revision, receipt_id, overlap_unresolved, serve_block_status (absent),
serve_source (none)`.

Four times are separate and never substituted for one another (R19, RB13):

- `target_anchor_date`: the declared event start; identifies the event, proves nothing.
- `completion_upper_bound`: the declared event end (`completion_basis = declared_event_end`);
  a bound, never a clock.
- `publication_upper_bound_utc`: the timestamp of the captured source revision; the result
  was public no later than this.
- receipt time: in the attempt receipt, referenced by `receipt_id`.

A row with no declared window has `overlap_unresolved = true` and is withheld from every
cutoff. Draw completeness is derived from the parsed bracket (every non-bye slot resolved
and the final decided), never from `draw_size - 1` alone.

Diff against the previous version, by `row_id`: `added`, `revised` (score/status/winner
changed; old bytes and the old version stay), `removed`, `duplicate` (same identity twice
in one capture), `unresolved` (identity quarantined), `conflicting` (two sources or two
templates disagree; both receipts kept, no winner chosen).

## 5. Fixture and eligibility

A fixture is `(tour, event_id, round, player_a_id, player_b_id, scheduled_start)` with
`fixture_id = sha256` of those fields in neutral orientation. Inputs carrying any outcome-like
column (`winner`, `score`, `a_won`, `result`, serve counts) are refused. Frozen exclusion
rule: unknown identity, unknown surface, unknown format evidence, or a scheduled start with
no source/timezone is `excluded` with the reason recorded; nothing is inferred.

Information cutoff for a fixture starting on date S: `cutoff = S − lag` with `lag = 2`
(R6/R12). A results row is eligible iff `completion_upper_bound <= cutoff` (inclusive, R17)
and `publication_upper_bound_utc <= issue_time` and `receipt_utc <= issue_time` and
`overlap_unresolved = false`. Serve state as-of a fixture is the last block whose event
window end resolves to `<= cutoff`; ranking as-of is the last list with
`ranking_date <= cutoff`. A results-only update never advances serve or ranking freshness.
The retained serve frontiers ATP 2026-05-17 and WTA 2026-05-18 are declared in the config
and compared with the feed, never assumed.

Rungs: `elo` runs end to end through `tennislab.ratings.elo` (fixed constants, no fit).
`atp_p0`, `atp_p1`, `atp_full_tier`, `wta_base`, `wta_full` emit an explicit
`forecast_unavailable` record naming the missing binding: the trunk has no single-fixture
feature route; the only exact route is appending the fixture to a live panel and replaying
the chain from `features` to `pipeline` with the fixture year's labels blank, which needs a
bound live panel and fitted artifacts that this lane does not fit (no refit, no new
candidate selection).

## 6. Ledger records and transitions

`ledger.jsonl`, one canonical JSON record per line. Every record: `schema_version`
(`ledger-1`), `seq`, `kind`, `subject_id`, `recorded_at_utc`, `payload`, `content_sha256`
(hash of kind + subject + payload), `previous_record_sha256`, `record_sha256`. Genesis
previous hash: `sha256("tennislab prospective ledger genesis v1")`; an empty or malformed
digest anywhere is refused on load. `verify` recomputes every hash, checks `seq`
contiguity and replays the transition table below; any failure names the record.

| Kind | Allowed after | Notes |
|---|---|---|
| `fixture_proposed` | nothing for the subject | first record of a fixture |
| `fixture_qualified` / `fixture_excluded` | `fixture_proposed` | exclusion carries the frozen reason |
| `forecast_issued` | `fixture_qualified` | one per rung; duplicate (same rung, same content) refused; different content for the same rung refused unless `supersedes` names the earlier record |
| `forecast_unavailable` | `fixture_qualified` | one per rung |
| `proof_requested` | `forecast_issued` | hash-only digest of the issue record |
| `proof_verified` / `proof_failed` | `proof_requested` | attestation time recorded separately from issue time |
| `start_verified` | `fixture_qualified` | independently established actual start with its source |
| `result_provisional` | `fixture_qualified` | first capture |
| `result_final` | `result_provisional` | confirmed by a second capture or declared finality rule |
| `result_corrected` | `result_final` | supersedes; nothing rewritten |
| `score_reported` | `result_final` or `result_corrected` | written only by `settle` after the barrier |

Barrier for a score: chain verifies; `forecast_issued.issued_at_utc < start_verified.actual_start_utc`;
`proof_verified.attested_time_utc < actual_start_utc`; result final. A forecast with a
pending, failed or late proof stays visible in `coverage.csv` as `unconfirmed` and is
never scored as confirmed prospective evidence. Estimand: completed matches; retirements,
walkovers, defaults and withdrawals are excluded with their counts.

Proof adapter: `offline` only in this lane. `proof_requested` writes
`proofs/<digest>.request.json`; `ledger proof-verify` reads an attestation JSON the owner
obtained outside this code (digest, attested time, method, evidence reference) and records
verified/failed. No data bytes ever leave the workspace; a live hash-only OpenTimestamps
adapter is a separate step under D30.

## 7. Acceptance criteria (each is a test through `tennislab.cli.main`)

1. results-only update from replayed responses: receipt, raw bytes, version, latest advanced
2. identical-content rerun: new receipt, identical normalized bytes, `no_change = true`
3. interrupted attempt: receipt `interrupted`, latest unchanged, retry in a new directory
4. revised score: `revised` in diff, earlier version and bytes intact
5. quarantined identity, duplicate and conflicting rows with both receipts
6. serve and ranking freshness unchanged by a results-only update; frontier compared, not assumed
7. event overlap and same-cutoff boundary: bound == cutoff eligible, bound == cutoff + 1 not; unknown window withheld
8. outcome-like input columns refused; no outcome field in any fixture or forecast record
9. player swap: same `fixture_id`, `p_a` mirrored
10. missing or ambiguous start excluded with reason
11. failed or late proof: never confirmed; visible in coverage
12. duplicate issuance refused
13. ledger tamper (edited payload, removed line, empty digest) fails `verify` naming the record
14. provisional → final → corrected settlement; retired and walkover excluded
15. report refusal before the barrier
16. planted-defect checks: every gate above rejects its planted defect
17. `make check` passes in a clean clone without archive, raw data or network
