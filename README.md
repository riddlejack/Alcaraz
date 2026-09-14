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
component metrics and the pipeline's selection-criterion scores are computed after the
barrier (values unchanged; the archive wrote them before it). `tests/test_barrier_gate.py`
demonstrates the clean run and planted leaks through the driver; the five Lane C2 gates
admitted with negative controls (T2, T9, T10, T11, T13) run on the committed synthetic
sample and fail, not skip, without it. Independent different-model review of this repair
is pending (`docs/DECISIONS.md` RB11, RB14); nothing here is a new result, and the
archive's 2025–2026 window is spent development data.

On the 18,882 priced ATP matches of 2017–2024 (match-weighted log loss, lower is better):
pooled Elo 0.6237, P0 0.6121, P1 0.6053, full_tier 0.5984, Pinnacle 0.5873.

## Run

```sh
make setup            # pinned environment from uv.lock (Python 3.14.6)
make test             # unit, regression, barrier-gate and integrity tests (about three minutes)
make reproduce-small  # the chain on the synthetic sample, one pinned number (about 40 s)
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
docs/            METHODS, RESULTS (generated), PROCESS, DECISIONS, INTEGRITY, EQUIVALENCE, ARCHIVE, PORTING
tools/           equivalence harness against the archive; the sample generator
```

## Licences

Code: MIT (`LICENSE`). Data: see `DATA_LICENSES.md`; nothing derived from odds providers
is redistributed, and Sackmann-derived tables are CC BY-NC-SA 4.0.
