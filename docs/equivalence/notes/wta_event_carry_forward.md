# wta_event_carry_forward (stage `event_carry_forward`, WTA)
Base revision: WTA02_models/wta_carry_event_crosswalk.py. There is no TIER01 counterpart of this file, so nothing was merged; the ATP tour has `tennislab.panel.crosswalk_carry` (see `event_carry_forward.md`).
Module: `tennislab.panel.wta_crosswalk_carry`. `wta_sources` is imported by name as `tennislab.sources.wta_sources` instead of loaded by path.
ATP TIER01/attempt_002: not this module — see `event_carry_forward.md`.
WTA WTA02/attempt_002: identical 3/4 (extended_wta_event_crosswalk.csv, stdout.txt, stderr.txt); differing: carry_forward_report.json (4 leaves — `inputs.code` was the archive file's path and hash and is now `code_receipt("tennislab.panel.wta_crosswalk_carry")`. `inputs.sources_module` is unchanged: the declared binding is still resolved and hash-verified. Every data leaf identical: 999 base rows, 88 carried (84 tier A, 4 tier B), 1,087 extended rows, 50 carried editions in 2025 and 38 in 2026, 4,395 tennis-data rows covered and 205 left unresolved.)
Label reads: none. The stage reads only the event-identity columns of each workbook — Location, Tournament, WTA number, Date, Tier, Court, Surface — and the mirror's edition identity.
Learned constants: none. A carried mapping is a declared assumption (`name_evidence = carried_forward_declared_assumption`), recorded as such in the report's `assumption` field, not a measurement.
Open: nothing.
