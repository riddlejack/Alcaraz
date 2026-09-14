# tennis-lab

A forecasting program for men's and women's professional tennis, designed for a leakage
audit and pre-registration. It measures how far public match statistics can take a
pre-match model, benchmarks it against published public models and the closing market,
and will record forecasts prospectively only after the pending integration gates close.

**Status (2026-09-14, branch `b2-integrity`): the trunk reproduces the archive's accepted
results and now enforces the report barrier at run time.** One package reruns the
accepted ATP run (TIER01/attempt_002, five bundles, 2017–2024) and the accepted WTA run
(WTA02/attempt_002, 2025–2026) from the same frozen inputs; every prediction file, the
primary contrasts, the pooled and annual metrics, the bootstraps and the reliability
tables reproduce byte-identically (`docs/EQUIVALENCE.md`). The historical baseline
`180cb2d` (tag `historical-baseline-180cb2d`) is kept for the reconstructor.

Lane B2 (decision RB14, `docs/INTEGRITY.md`): the chain driver derives each stage's
outcome access from an audit hook on file opens and fails an undeclared read; fit and
selection stages read outcomes only through fold-specific accessors with receipts; the
barrier refuses to freeze a run tree that carries any metric-shaped artifact. SR03
component metrics are computed after the barrier; selection-criterion scores are
recomputed and published there after being used in memory for selection. The archive
wrote these scores before the barrier. `tests/test_barrier_gate.py`
demonstrates clean runs and controlled violations through the driver. Four scoped C2
ports (T9, T10, ATP T11/T13) and the separately repaired T2 dtype sentinel run on the
committed synthetic sample and fail without it. The different-model review found and
prompted further runtime repairs (RB16, `docs/B2_REVIEW.md`). Independent review, fresh
historical reconstruction and native ATP tier/WTA base T1 checks are complete. B2 is
accepted for local integration; WTA tier and full-bundle T3 remain open under RB9. These are software integrity checks, not a new scientific
result; the archive's 2025–2026 window is spent development data.

On the 18,882 priced ATP matches of 2017–2024 (match-weighted log loss, lower is better):
pooled Elo 0.6237, P0 0.6121, P1 0.6053, full_tier 0.5984, Pinnacle 0.5873.

## Run

```sh
make setup            # pinned environment from uv.lock (Python 3.14.6)
make test             # unit, regression, barrier-gate and integrity tests (about eight minutes)
make reproduce-small  # the chain on the synthetic sample, one pinned number (about 40 s)
make reproduce-tier   # the same with the five tier stages on data/sample_tier (about 90 s)
```

Reproducing the accepted runs needs a local copy of the research archive (see
`docs/ARCHIVE.md`):

```sh
export TENNISLAB_ARCHIVE=/path/to/the/archive
uv run python tools/equivalence.py chain --run TIER01/attempt_002 \
  --chain-config "$TENNISLAB_ARCHIVE/experiments/runs/TIER01/attempt_002/chain_tier01_run_002.json"
uv run tennislab report --ladder --runs ATP=<run root> WTA=<run root>
```

## Layout

```
src/tennislab/   one package: sources, panel, chronology, ratings, dynamics, features,
                 models, evaluation, chain, cli
configs/         one file per model configuration (elo, atp_p0, atp_p1, atp_full_tier,
                 wta_base, wta_full)
data/manifests/  receipts and hashes still referenced by the trunk
data/sample/     small redistributable sample so CI runs without the full data
data/sample_tier/ the second synthetic scenario: the same world with a lower tier (RB9)
docs/            METHODS, RESULTS (generated), PROCESS, DECISIONS, INTEGRITY, EQUIVALENCE, ARCHIVE, PORTING
tools/           equivalence harness against the archive; the sample generator
```

## Live update, prospective fixtures and the ledger (Lane D repair)

Verified on the synthetic rehearsal world only; no campaign is registered and no real
forecast has been issued. The original `docs/live/DESIGN.md` and `docs/live/FREEZE.json`
are preserved with the rejected `50518be` attempt. `docs/live/REPAIR.md` and
`docs/live/REPAIR_FREEZE.json` bind the repair; `configs/live/live.json` is the
manifest-bound configuration.

```sh
uv run tennislab update   --config configs/live/live.json --events events.json --replay <dir>
uv run tennislab fixture  --config configs/live/live.json --input pending.csv --batch-id b1
uv run tennislab forecast --config configs/live/live.json --batch-id b1
uv run tennislab ledger   verify --config configs/live/live.json
uv run tennislab settle   results|score|report --config configs/live/live.json
```

What is demonstrated by `tests/live/`: a versioned results-only refresh with immutable
attempt receipts and retained bytes; hash binding and re-verification of each receipt;
identical-content reruns; interrupted attempts that never become latest; revisions without
history loss; quarantine of ambiguous identities, duplicates and conflicts; serve/ranking
freshness that a results-only update cannot advance; typed completion, publication,
receipt, played-status and overlap eligibility for both bound history and incremental
rows; an IANA-timezone-derived D−2 cutoff; outcome-free fixtures whose bytes and stable
identity are checked against the ledger qualification; field-level source qualification;
confined output IDs and symlinks; duplicate issuance and ledger tamper refusal; late or
failed proofs kept unconfirmed; provisional, final and corrected settlement; and report
refusal before the barrier. Only the `elo` rung issues a forecast; every other rung writes
an explicit unavailable record (see RB18–RB19).

## Licences

Code: MIT (`LICENSE`). Data: see `DATA_LICENSES.md`; nothing derived from odds providers
is redistributed, and Sackmann-derived tables are CC BY-NC-SA 4.0.
