# event_carry_forward
Base revision: TIER01_models/carry_event_crosswalk.py, revision 7 (the WTA02_models copy of that file is byte-identical, so there is one revision and nothing to merge). The WTA tour has its own carry-forward program; see `wta_event_carry_forward.md`.
Module: `tennislab.panel.crosswalk_carry`. `join_candidates.normalized` is imported by name from `tennislab.panel.join` instead of being loaded by path.
ATP TIER01/attempt_002: identical 3/4 (extended_event_crosswalk.csv, stdout.txt, stderr.txt); differing: carry_forward_report.json (2 leaves — the archive listed its own source file inside the `inputs` path->sha256 map; the port keeps `inputs` a pure map of the three data inputs and records `code_receipt("tennislab.panel.crosswalk_carry")` under a new `code` key. Every data leaf identical, including the no-op result: 1,056 base rows carried forward unchanged, `carried_rows` 0.)
WTA WTA02/attempt_002: not this module — see `wta_event_carry_forward.md`.
Label reads: none. The stage reads event names, mirror edition names and join classifications only.
Learned constants: none.
Open: nothing.
