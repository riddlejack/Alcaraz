# tennis-lab

**How far can public tennis statistics take a pre-match forecast?** tennis-lab tests that
question with a chronological model ladder: start with Elo, add a boosted model over
results and match context, replay dynamic serve/return states, then incorporate richer
lower-tour histories. Frozen experiments and independent reconstruction keep both the
result and the failures that changed the system traceable.

On the same priced retrospective matches, every added statistics rung lowered log loss,
but the best sports rung remained behind the normalised Pinnacle reference. The prices
are closing-like annual observations without verified quote times, so this is a model
comparison on exposed development data—not a synchronized market test or prospective
record.

## Result, on the same priced matches

Match-weighted log loss; lower is better. These are exposed retrospective cohorts, and
the market prices are closing-like annual observations without verified quote times.

| Tour and target years | Matches | Elo | base | full | full_tier | Pinnacle |
|---|---:|---:|---:|---:|---:|---:|
| ATP, 2017–2024 | 18,882 | 0.6237 | 0.6121 | 0.6053 | 0.5984 | 0.5873 |
| WTA, 2025–2026 | 2,344 | 0.6265 | 0.6230 | 0.6153 | — | 0.5953 |

`tennislab report --ladder` generates the source table and machine-readable values in
[`docs/RESULTS.md`](docs/RESULTS.md) and [`docs/ladder.json`](docs/ladder.json). The ATP
chart below uses each year's identical priced cohort; years share players and model
ancestry, so this is robustness evidence, not eight independent replications.

![ATP full-tier model and normalised Pinnacle log loss by year](docs/assets/atp_full_tier_vs_market.svg)

Regenerate the chart with `uv run python tools/render_ladder_chart.py`. It reads only
`docs/ladder.json`; no result is typed into the graphic.

The comparison says how this model scored relative to a strong market reference. Because
the price and model cutoffs are not synchronized, it does not identify market efficiency.
Lane G has completed the external-benchmark inventory and comparison design; adapter
implementation, frozen execution, and an accepted matched comparison remain pending.

## How the evidence was built

The product rebuild uses one Python trunk with versioned configurations, fold-specific
outcome-read receipts, a forecast-before-score barrier, re-hashed manifests, and planted
defects for admitted integrity checks. Independent reconstruction matched the accepted
forecast files, final reports, and training-key files byte for byte. Separately, fitted
estimators had adjudicated signed-zero/pickle-memo differences, and WTA source hashes had
a documented workbook-provenance cascade; neither exception applies to those exact
forecast/report/training-key matches. The engineering contract and its open scope are in
[`docs/METHODS.md`](docs/METHODS.md), [`docs/PROCESS.md`](docs/PROCESS.md), and
[`docs/INTEGRITY.md`](docs/INTEGRITY.md).

## Release status on 2026-09-14

- **Retrospective trunk:** reconstructed and accepted within the documented integrity
  scope.
- **Live/snapshot path:** under repair. The first implementation and its first repair were
  rejected in independent review; the real-history, six-rung D2 snapshot remains
  incomplete.
- **Prospective evidence:** none. No real forecast batch has been issued and scored.
- **Data horizon:** the date of this repository is not the model's through-date. The ATP
  run uses a 2005–2024 panel with 2017–2024 targets. The WTA run uses a 2007–2026 panel
  with 2025–2026 targets, but that window is exposed development evidence with known
  chronology defects. The Tennis Abstract crawl and TennisMyLife files are not integrated
  into either accepted run; [`docs/DATA.md`](docs/DATA.md) separates acquisition,
  qualification, and use.
- **Hosted CI:** green on tested commit
  `4c83d283290dcdb8977ca455aebf9506e4d3cc6e`. GitHub Actions run
  [`34903105291`](https://github.com/riddlejack/tennis-lab/actions/runs/34903105291)
  installed Python 3.14.6, passed lint, reported 434 tests passed with one optional skip,
  and passed both committed-sample reproductions.

## Run the engineering harness

Python 3.14.6 is required by the locked environment.

```sh
make setup
make test
make reproduce-small
make reproduce-tier
```

The two sample reproductions invoked above are synthetic. They test the chain, integrity
controls, and pinned arithmetic; they say nothing about predictive performance on real
tennis. Full historical reconstruction additionally needs the separate research archive
as described in [`docs/ARCHIVE.md`](docs/ARCHIVE.md).

## Read next

- [`docs/METHODS.md`](docs/METHODS.md): populations, information sets, fitting, scores,
  uncertainty, and claim limits.
- [`docs/PROCESS.md`](docs/PROCESS.md): the LLM-assisted build, the leaks and engineering
  failures reviewers found, and the rules that replaced them.
- [`docs/DATA.md`](docs/DATA.md): actual source and tour horizons, qualification state,
  chronology limits, and the unfinished snapshot path.
- [`DATA_LICENSES.md`](DATA_LICENSES.md): attribution and redistribution boundaries.

## Licence and attribution

Code is MIT-licensed. Raw source data and restricted odds-provider rows are not
redistributed. Source-specific terms and the tracked-artifact inventory are in
[`DATA_LICENSES.md`](DATA_LICENSES.md).

> Data by Jeff Sackmann / Tennis Abstract, collected with the site owner's permission
> under `PERM-TA-001`, as supplemented by `PERM-TA-002`. Any published derived table must
> carry this attribution and its applicable licence. The collection is not part of the
> accepted retrospective model runs described above.
