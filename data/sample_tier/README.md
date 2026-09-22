# Synthetic tier sample

Everything in this directory is synthetic. `tools/make_sample.py --scenario tier` draws
the players, events, results, serve counts, rankings and prices from
`numpy.random.default_rng(20260913)`; no real player, match, result, ranking or market
price appears here, and nothing in it is evidence about tennis. It is the second
committed scenario (decision RB9): the base world of `data/sample` with a lower tier
beneath it, so that `make reproduce-tier` and `tests/test_tier_scenario.py` can drive the
five TIER01 stages (`tier_stream`, `tier_elo`, `sr02_tier_replay`,
`sr02_tier_noqual_replay`, `tier_block`) through the real chain driver on a clean clone
without the research archive. `data/sample` is untouched by this scenario.

Regenerate in place with `uv run python tools/make_sample.py --scenario tier`; the
generator re-pins every sample hash in `configs/chains/sample_atp_tier.json`, measures
the per-training-window initial-rating offsets it declares there, and writes
`manifest.json` (the sha256 of each file and the offsets). `tests/test_tier_scenario.py`
checks that the committed files are exactly the generator's output.

## Contents

The base-scenario files (`panel.csv`, `base_rules.csv`, `rules.json`, `sr02_primary.json`,
`selections.csv`, `players.csv`, `design.md`, `panel_manifest.json`) play the same roles
as in `data/sample/README.md`. What the tier scenario adds:

| File | Read by | Contents |
|---|---|---|
| `archive.tar.gz` | `rankings`, `tier_stream` | the base members plus `atp/atp_matches_qual_chall_YYYY.csv` and `atp/atp_matches_futures_YYYY.csv` for 2008–2020: 6,422 lower-tier rows |
| `snapshot_file_inventory.csv` | `tier_stream` | every tarball member's path, bytes, sha256, git blob sha1 and mode (the ARCHIVE01 inventory shape) |
| `archive_manifest.json` | `tier_stream` | pins the tarball and the inventory at their hashes (the ARCHIVE01 manifest shape) |
| `expected.json` | `tennislab reproduce-small --scenario tier` | the pinned headline (below) |
| `manifest.json` | `tests/test_tier_scenario.py` | generator receipt: seed, counts, file hashes, measured offsets |

World: 120 players, 50 on the tour from 2011, 40 who reach a tour main draw in a later
season after lower-tier seasons, 30 who never do. Beneath the 25 tour events per season:
qualifying rounds `Q1..Q3` (a draw of eight) at every tour event under the main draw's
own `tourney_id` and level, so the same-event-qualifying ablation removes rows; ten
Challenger main draws (`tourney_level = C`, draw 16); eight Futures draws; and two
satellite circuits per season whose legs share one anchor (ids `<base>-<YYYY><leg>`),
which `satellite_circuit_dating` redates to the circuit's end. Serve-count blocks appear
in the qualifying/Challenger family from 2012 (85% of rows) and never in Futures; 1.5%
of lower-tier rows are walkovers, which `tier_stream` excludes. Grand slams span two
weeks so that their semifinals and finals fall after the qualifying rows' reported date
(anchor + 7) and the ablation has targets whose event term the qualifying rows could
have updated.

## The declared offsets

The chain config carries `tier_offset_mode: per_training_window` and
`tier_initial_rating_offset_by_year`, which the generator measures by running the
package's own `tier_stream` on the written tarball and `tier_elo.measure_offset` on its
stream at every horizon `tier_elo` uses (the day before each raw model year's training
window starts). Seasons 2011–2016 measure through 2010, before any Elo-eligible
lower-tier row, so their offset is 0.0 by the declared empty-window rule; 2017–2020
measure through 2011–2014. `tier_elo` re-measures at run time and refuses a declared
value that drifts by more than 1e-6.

## Pinned headline

`expected.json` was pinned by `uv run tennislab reproduce-small --scenario tier --pin`
on the pinned environment (`uv.lock`: Python 3.14.6, numpy 2.5.3, scipy 1.18.1,
scikit-learn 1.9.1) and is compared to 1e-9:

- primary contrast `full_tier_minus_full`, HGB learner, aligned primary 2018–2020,
  n = 1,582: equal-year log-loss delta `-0.0005904833739188241`, match-weighted
  `-0.0005860217432911288`
- pooled match-weighted log loss on the primary-priced rows: base `0.5463693339215431`,
  full `0.5471414504637202`, base_tier `0.545810160295632`, full_tier
  `0.5463798882973111`, full_tier_noqual `0.5468157151520708`, calibrated Pinnacle
  `0.5393907024219846`

The run takes about 90 seconds. A synthetic world says nothing about real tennis: that
the tier bundle happens to beat the full bundle here is a reproduction check, not a
result.

## The entry/level rehearsal (`--scenario tier_entry`)

`configs/chains/sample_atp_tier_entry.json` binds this same sample with the features
stage's `entry_level_block: true` and the bundles `base`, `full_tier` and
`full_tier_entry` (ARMS01 Arm 1: `full_tier` plus signed Q/LL/WC/PR entry differences,
the symmetric any-qualifier flag and G/M/A/F level indicators). The generator draws
`Q` and `WC` entries and `G`/`M`/`A` levels, so `LL`, `PR` and `F` are all-zero here.
`expected_entry.json` was pinned by `uv run tennislab reproduce-small --scenario
tier_entry --pin` on the same environment: primary contrast
`full_tier_entry_minus_full_tier`, n = 1,582, equal-year log-loss delta
`2.6090446254779006e-05`; pooled base `0.5463693339215431`, full_tier
`0.5463798882973111`, full_tier_entry `0.546330119662121`, calibrated Pinnacle
`0.5393907024219846`. The `base`, `full_tier` and Pinnacle values equal the tier
scenario's pins exactly and the 32 `base`/`full_tier` forecast files are byte-identical
between the two runs: appending the block changes nothing for a bundle that does not
read it. The sign of the entry contrast on this synthetic world is noise, not a result.
`tests/test_entry_scenario.py` drives this configuration through the chain driver.
