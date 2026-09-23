# One WTA 2024 buildoak historical comparison

This task-scoped adapter extends the accepted ATP 2024 comparison to the exact
2,404 qualified WTA 2024 keys. It preserves the native WTA weighted ensembles,
ordered specialists and recent-history activation. It does not change the
released Tennis Lab predictor. The copied buildoak formula projection retains
its source license in `runtime/adapter/LICENSE.buildoak`.

`prepare.py` extracts exact annual main-draw members from the pinned archive,
qualifies reported-date joins, retains duplicate historical keys through
transport-only source-row IDs, projects the chronological replay schedule and
sorts/deduplicates native rankings. It does not generate model scores.

`runtime/empirical_controller.py` sends released history and neutral fixtures to
isolated workers, then records forecast commitment. `runtime/verify_commitment.py`
checks that commitment read-only. `freeze.py` requires the independent review's
exact code/evidence hashes, verifies container files, then freezes one executable
attempt. `score.py` requires the commitment and bound sources before it computes
paired scores, intervals, coverage and fixed exploratory diagnostics.

All empirical inputs, caches, configurations, attempts and outputs live outside
this checkout in the explicitly assigned archive work directory. The code uses
explicit paths; it neither updates central project records nor merges itself.
Exact execution commands and results are in that work directory's `RUN.md` and
`RESULT.md`, with an integration handoff identifying the local commit.

The comparison is exposed retrospective development. Source settings were
published after the target year; historical date proxies are not verified
publication times. Proper scores and conditional intervals do not establish
prospective superiority, market edge, or an identical-input algorithm effect.
