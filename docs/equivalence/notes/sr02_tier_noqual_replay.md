# sr02_tier_noqual_replay
Base revision: TIER01_models/sr02_replay.py run with `sr02_replay.tier_feed.enabled = true` and `tier_feed.exclude_same_event_qualifying = true` (same module as sr02_replay, `tennislab.dynamics.replay`). The ablation drops every feed row whose `tourney_id` is a panel main draw's (such a row would update the event's latent term, so it is not purely player-state information); the same-event membership is read off the unfiltered feed, so this replay declares the same `same_event_qualifying_membership.csv` as sr02_tier_replay while counting the rows it excluded in `tier_feed.counters`.
ATP TIER01/attempt_002: identical 8/9 (selected_matches.csv, selection_map.csv, selection_carry_forward.csv, stale_state_rows.csv, same_event_qualifying_membership.csv, tier_feed_rule_basis.json, stdout.txt, stderr.txt); differing: run_manifest.json (7 leaves, all under `code`: replay/dynamic/path_runner receipts and `declared_binding`) — provenance only. Solver receipts, feed counters (13,641,497 service points available after the exclusion) and stale-state counts are identical.
WTA WTA02/attempt_002: not a WTA02 stage.
Label reads: none.
Learned constants: none.
Open: nothing.
