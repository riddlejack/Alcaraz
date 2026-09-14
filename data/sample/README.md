# Synthetic sample

Everything in this directory is synthetic. `tools/make_sample.py` draws the players,
events, results, serve counts, rankings and prices from `numpy.random.default_rng(20260913)`;
no real player, match, result, ranking or market price appears here, and nothing in it is
evidence about tennis. It exists so that `make reproduce-small` and the label-barrier test
(`tests/test_label_barrier.py`) can run the ported chain from `rule_mapping` to `report`
on a clean clone without the research archive.

Regenerate in place with `uv run python tools/make_sample.py`; the generator re-pins every
sample hash in `configs/chains/sample_atp.json` and writes `manifest.json` (the sha256 of
each file). `tests/test_reproduce_small.py` checks that the committed files are exactly the
generator's output.

## Contents

| File | Read by | Rows |
|---|---|---|
| `panel.csv` | `rule_mapping` (as base and extended panel), `sr02_replay`, `sr03_calibration`, `features`, `sidecar` | 5,350 matches, seasons 2011–2020, in the `format_corrections` panel schema (100 columns) |
| `base_rules.csv` | `rule_mapping` | 4,815 rule rows for seasons 2011–2019; 2020 is carried forward (520 carried, 15 tour-default rows for a new event) |
| `rules.json` | `rule_mapping` | the rule config: ordinary best-of-three and the four grand-slam codes |
| `sr02_primary.json` | `sr02_replay`, `sr03_calibration` | the frozen SR02 primary config (one dynamic and one control candidate) |
| `selections.csv` | `sr02_replay` | the saved candidate per family and selection year 2011–2020 |
| `players.csv` | `sidecar` | 60 players: id, name, hand, DOB, height; also the tarball's `atp/atp_players.csv` |
| `archive.tar.gz` | `rankings` | Sackmann-layout members: weekly Monday rankings 2011–2020 (31,320 rows), one match file per season, the player master and four document members |
| `design.md` | `features`, `sr03_calibration`, `sidecar` (bio contract), `predictor_config` | the bound design note |
| `panel_manifest.json` | `features` | the panel's declared hash and row count |
| `expected.json` | `tennislab reproduce-small` | the pinned headline (below) |
| `manifest.json` | `tests/test_reproduce_small.py` | generator receipt: seed, counts, file hashes |

World: 60 players with latent strengths and small surface deviations; 25 events per
season (4 `G` best-of-five draws of 32, 6 `M` draws of 32, 15 `A` draws of 16) on the four
surfaces, indoor and outdoor; brackets seeded by strength; outcomes drawn from the latent
win probability; serve counts drawn to satisfy the panel stage's identity constraints;
2.5% retirements, 0.5% defaults with commencement evidence, 1.5% count blocks missing,
1.5% provisional identities; Pinnacle prices on 95% of rows and B365 on 97%, both with an
overround; weekly rankings from strength plus a slow random walk.

## Pinned headline

`expected.json` was pinned by `uv run tennislab reproduce-small --pin` on the pinned
environment (`uv.lock`: Python 3.14.6, numpy 2.5.3, scipy 1.18.1, scikit-learn 1.9.1)
and is compared to 1e-9:

- primary contrast `full_minus_base`, HGB learner, aligned primary 2018–2020, n = 1,578:
  equal-year log-loss delta `0.0010578138814451785`, match-weighted `0.001057453523051042`
- pooled match-weighted log loss on the 1,497 primary-priced rows: base `0.5914863419162002`,
  full `0.5927031112270136`, calibrated Pinnacle `0.5717053594438446`

A synthetic world says nothing about real tennis: the full bundle happens to lose to the
base bundle here, which is the point of a reproduction check, not a result.
