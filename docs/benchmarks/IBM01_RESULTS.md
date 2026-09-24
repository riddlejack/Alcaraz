# Grand Slams 2022–2023: Alcaraz, Pinnacle and IBM's Match Insights on the same matches (IBM01)

> Superseded as the IBM comparison by [IBM02](IBM02_RESULTS.md) (64 matches, pooled with the
> 2023 files recovered from wimbledon.com). This page is retained as the archived-only result.

> **Independently reconstructed (archive decision D135).** Every number on this page comes
> from the single registered scoring pass of IBM01 ([ibm01.json](ibm01.json)). The
> population was frozen from start-time evidence before any Alcaraz forecast, price or
> label on these rows was read, and a separate implementation reproduced every estimate
> (the reconstruction also found that lab match ids repeat across tours; the scorer was
> re-keyed by tour and id and its output did not change).

IBM publishes a pre-match "Likelihood to Win" for Grand Slam singles matches at Wimbledon
and the US Open. The published files are not archived by IBM, but the Internet Archive
holds the ones that visitors happened to save. Every such file the archive's index lists
for 2021 to 2025 was recovered: 37, from Wimbledon 2023 and 2024 and the US Open 2022 and
2023, both tours. All 37 join to matches in this repository's history.

## Registered outcome

On the 29 matches whose IBM file was published before the first ball, log loss was
**0.4550 (Alcaraz), 0.4394 (Pinnacle) and 0.6285 (IBM)**; Alcaraz minus IBM **−0.1735
[−0.2383, −0.1074]**; Pinnacle minus IBM −0.1891 [−0.2471, −0.1286]; Alcaraz minus
Pinnacle +0.0156 [−0.0210, +0.0544]. This is a descriptive comparison on an
archive-selected sample of marquee matches, not a benchmark of IBM's system across a draw.

| System | Log loss | Brier | Correct picks |
|---|---:|---:|---:|
| Pinnacle closing price, normalised | 0.4394 | 0.1389 | 24 of 29 (82.8%) |
| Alcaraz (`full_tier_entry` ATP, `full_entry` WTA), issued two days before the match | 0.4550 | 0.1452 | 23 of 29 (79.3%) |
| IBM Match Insights, published before the first ball | 0.6285 | 0.2177 | 22 of 29 (75.9%) |

Sensitivities: on the 19 matches where the archive itself captured IBM's file before the
first ball, Alcaraz minus IBM is −0.1389 [−0.2310, −0.0488]; on all 36 mapped captures
regardless of timing, −0.1665 [−0.2302, −0.1046]. A cluster bootstrap by tournament-day was
run and is not reported: eight uneven clusters make it unstable.

## Why the gap is that large

IBM's numbers are hedged. Its favourite averages 58% (never above 72%); Alcaraz's averages
68% and Pinnacle's 69%. The three systems pick nearly the same winners (IBM and Pinnacle
agree on 25 of 29), so the accuracy gap is small; the log-loss gap is the price of stating
a 58% chance for matches that are won by the favourite four times in five. When its pick
was right, IBM still scored 0.547 per match against Alcaraz's 0.353.

## Population and timing

The 37 recovered files carry `win_prob_prematch` for both players and a publication
timestamp. For each match, the archived order of play, completed-match and
point-by-point feeds fixed the first-ball time (121 archive fetches, receipts kept):
19 files were saved by the archive before the first ball or published before the
official first point; 10 (US Open 2022 third round) were published at least 2.7 hours
before the session; 6 were rewritten during play (published one to six minutes before
the last point) and one three days after the match, so those seven are excluded; one
(Wimbledon 2023 Tiafoe v Dimitrov, rain-split) could not be resolved and is excluded.
Rounds in the primary 29: third round 17, fourth round 9, first round 1, quarter-final
1, final 1; 16 men's and 13 women's.

The Alcaraz forecasts are the saved frozen-model outputs for those seasons, issued at the
two-day cutoff; no refit. One retirement (Khachanov v Draper, 2022) is scored as in every
comparison here. Pinnacle's quote time is unknown, as everywhere in this
repository. The 2022–2023 seasons are development data for Alcaraz; IBM's numbers were
never an input to any model here.

## Limits

- Twenty-nine matches. The interval is wide and the sample is whatever visitors chose to
  archive: later rounds and famous names, where favourites are strong.
- IBM's product is a fan-facing likelihood, not a published forecasting benchmark; its
  hedging may be deliberate. The comparison is on proper scores, which is what a
  probability is for.
- A full-draw comparison would need IBM's complete 2023–2024 files. The Slam sites may
  still serve them; their terms of use have not been read, so no live request was made.

Evidence in the research archive: `data/raw/IBM01/` (raw captures, join, start-evidence
bytes with manifests), `experiments/IBM01.design.md`, `references/IBM01/` (freeze,
scorer, result, reconstruction). Machine-readable aggregates: [ibm01.json](ibm01.json).
