# rule_mapping
Base revision: TIER01_models/carry_rule_rows.py (the WTA02_models copy of that file is byte-identical, so there is one revision and nothing to merge). The WTA tour has no base mapping to extend and generates its rule rows instead; see `wta_rule_mapping.md`.
Module: `tennislab.panel.rules`.
ATP TIER01/attempt_002: identical 5/6 (rules.csv, rule_rows_carried_forward.csv, rule_rows_tour_default.csv, stdout.txt, stderr.txt); differing: manifest.json (5 leaves — `inputs.code` was the archive file's path and hash and is now `code_receipt("tennislab.panel.rules")`, and `manifest_sha256_of_inputs` is the canonical hash *of that map*, so it moves with it. Every other leaf identical: 51,222 total rule rows, 0 carried, 0 tour-default, 0 refused for the 2024 horizon.)
WTA WTA02/attempt_002: not this module — see `wta_rule_mapping.md`.
Label reads: none. The stage uses only `(source_season, tourney_id, tourney_name, tourney_level, round, best_of, source_key, match_id)`.
Learned constants: none. The carried rule is inherited from a real prior edition and each carried row records `carried_from_source_season`/`_tourney_id`/`_tourney_name`; a row with no carry source and no tour default is refused rather than guessed.
Open: nothing.
