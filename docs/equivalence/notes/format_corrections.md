# format_corrections
Base revision: WTA02_models/apply_format_corrections.py (WTA02 additions merged: none needed — the WTA02 copy is a strict superset of TIER01_models/apply_format_corrections.py. The 81-line diff is the WTA docstring plus the `tour` switch, `run_wta` and its dry-run branch; the ATP branch is identical between the copies.)
Module: `tennislab.panel.format_corrections`, serving both tours.
ATP TIER01/attempt_002: identical 4/4 (panel.csv, manifest.json, stdout.txt, stderr.txt). 51,222 rows, the four guarded 2007/2012 `best_of` corrections applied, panel sha256 708c18ac… as the archive recorded.
WTA WTA02/attempt_002: identical 4/4 (panel.csv, manifest.json, stdout.txt, stderr.txt). 46,827 rows, no declared correction, best-of-three verified, panel sha256 283740365f… as the archive recorded.
Nothing was added to the manifest: the archive recorded no code receipt for this stage and no config field pins a module, so the manifest is the archive's bytes.
Label reads: none. The stage copies panel rows through and rewrites one metadata field.
Learned constants: none. `CASE_IDS` stays a literal — four named, dated matches, with every guard (`assert_before_best_of == 5`, the replacement, the source file hash, the source line number, the match date and the round) unchanged.
Open: nothing.
