# tennis-lab

A leak-audited, pre-registered forecasting program for men's and women's professional
tennis that measures how far public match statistics can take a pre-match model,
benchmarks it against published public models and against the closing market, and records
every forecast prospectively.

**Status: rebuild in progress.** This repository is being reconstructed, stage by stage,
from the research archive so that one package reproduces the archive's accepted results
from the same frozen inputs. `docs/EQUIVALENCE.md` records which stages reproduce
byte-identically and which differ, with the cause. Nothing here is a new result.

## Run

```sh
make setup            # pinned environment from uv.lock (Python 3.14.6)
make test             # unit tests
make reproduce-small  # one headline number from the committed sample
```

## Layout

```
src/tennislab/   one package: sources, panel, chronology, ratings, dynamics, features,
                 models, evaluation, chain, cli
configs/         one file per model configuration (elo, atp_p0, atp_p1, atp_full_tier,
                 wta_base, wta_full)
data/manifests/  receipts and hashes still referenced by the trunk
data/sample/     small redistributable sample so CI runs without the full data
docs/            METHODS, RESULTS, PROCESS, DECISIONS, EQUIVALENCE, ARCHIVE
```

## Licences

Code: MIT (`LICENSE`). Data: see `DATA_LICENSES.md`; nothing derived from odds providers
is redistributed, and Sackmann-derived tables are CC BY-NC-SA 4.0.
