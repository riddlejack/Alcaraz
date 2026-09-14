# tennis-lab

A forecasting program for men's and women's professional tennis, designed for a leakage
audit and pre-registration. It measures how far public match statistics can take a
pre-match model, benchmarks it against published public models and the closing market,
and will record forecasts prospectively only after the pending integration gates close.

**Status (2026-09-14): the trunk is rebuilt and reproduces the archive's accepted results.**
One package reruns the accepted ATP run (TIER01/attempt_002, five bundles, 2017–2024) and
the accepted WTA run (WTA02/attempt_002, 2025–2026) from the same frozen inputs through
the ported chain driver; every prediction file, the primary contrasts, the pooled and
annual metrics, the bootstraps and the reliability tables reproduce byte-identically.
An independent fresh clone passed lint, 327 tests (one archive-dependent skip), and the
synthetic reproduction on 2026-09-14. **Integration acceptance remains pending:** SR03
still writes metrics before the report barrier, and Lane C's initial integrity suite
was rejected after planted leaks escaped detection. The existing tests establish their
stated cases, not a comprehensive leak audit; see `docs/DECISIONS.md` RB9–RB13.
The remaining differences are named provenance fields (code receipts, hash cascades from
two artifacts that are now timestamp-free). `docs/EQUIVALENCE.md` records every stage;
`docs/RESULTS.md` is the generated ladder. Nothing here is a new result; the archive's
2025–2026 window is spent and every number is exposed development data.

On the 18,882 priced ATP matches of 2017–2024 (match-weighted log loss, lower is better):
pooled Elo 0.6237, P0 0.6121, P1 0.6053, full_tier 0.5984, Pinnacle 0.5873.

## Run

```sh
make setup            # pinned environment from uv.lock (Python 3.14.6)
make test             # unit, regression and label-barrier tests (about two minutes)
make reproduce-small  # the chain on the synthetic sample, one pinned number (about 35 s)
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
docs/            METHODS, RESULTS (generated), PROCESS, DECISIONS, EQUIVALENCE, ARCHIVE, PORTING
tools/           equivalence harness against the archive; the sample generator
```

## Licences

Code: MIT (`LICENSE`). Data: see `DATA_LICENSES.md`; nothing derived from odds providers
is redistributed, and Sackmann-derived tables are CC BY-NC-SA 4.0.
