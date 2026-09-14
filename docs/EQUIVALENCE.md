# Equivalence with the archive's accepted runs

Oracle: every stage of every accepted archive run wrote `stage_manifest.json` with the
SHA-256 of each output file. A ported stage is run on the same frozen inputs and every
output file is compared by hash. Status is one of: **identical**, **explained** (differs
only in named provenance fields, with the cause), or **open** (an unexplained difference,
which blocks the next stage).

Provenance classes that are expected to differ and are not evidence of a numerical
change: the program path and hash of the code that ran, the Python interpreter path,
wall-clock timestamps, and the run root path when it is written into a manifest.

## ATP — `TIER01/attempt_002`

| # | Stage | Status | Data outputs | Cause of difference |
|---|---|---|---|---|
| 1 | bridge | pending | | |
