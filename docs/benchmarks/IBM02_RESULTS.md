# Grand Slams 2022–2023: every recoverable pre-match IBM forecast, pooled (IBM02)

> **Independently reconstructed (archive decision D136).** Every number on this page comes
> from the single registered scoring pass of IBM02 attempt 002 ([ibm02.json](ibm02.json)).
> The population was frozen from first-play evidence before the pass; a separate
> implementation reproduced every point estimate exactly. The narrower first result on the
> 29 archived files is [IBM01](IBM01_RESULTS.md) (D135); this page supersedes it as the
> IBM comparison.

## What was recovered, and why most of it cannot be used

IBM publishes a pre-match "Likelihood to Win" for Grand Slam singles at Wimbledon and the
US Open. Two sources were used. The Internet Archive holds 37 files that visitors saved
(29 of them provably pre-match, the IBM01 population). wimbledon.com still serves the
complete per-match files for 2023, 2024 and 2025 (749 files, pulled under the AELTC terms
of use for personal, non-commercial research; usopen.org's terms forbid automated
extraction, so no live request was made there).

The live files turned out to be mutable. Every 2024 file was re-published on 17 July
2024, three days after the final, and every 2025 file on 30 July 2025. For 2023 the files
carry per-day timestamps, but for the twelve matches the archive had also captured the
evening before, eight live values differ from the archived pre-match copy, by up to 0.15:
IBM rewrites its number on match day. A live file therefore counts only when its last
publication can be shown to precede the first ball. The archived official order-of-play
and completed-match feeds establish that for 36 of the 253 live 2023 files; for 211,
mostly matches suspended overnight whose file was published within minutes of the court's
scheduled start, the first ball cannot be documented, and 5 were published during or after
play. Nothing from 2024 or 2025 qualifies.

## Registered outcome

On the 64 matches with a provably pre-match IBM probability (29 archived, 36 live, one
overlap; 2022 US Open, 2023 US Open and 2023 Wimbledon; both tours):

| System | Log loss | Brier | Correct picks |
|---|---:|---:|---:|
| Pinnacle closing price, normalised | 0.4876 | 0.1624 | 76.6% |
| Alcaraz (`full_tier_entry` ATP, `full_entry` WTA), issued two days before the match | 0.5154 | 0.1732 | 68.8% |
| IBM Match Insights, published before the first ball | 0.6012 | 0.2065 | 71.9% |

Alcaraz minus IBM **-0.0858 [-0.1468, -0.0188]**; Pinnacle minus IBM
-0.1136 [-0.1718, -0.0513]; Alcaraz minus Pinnacle
+0.0278 [-0.0015, +0.0582]. 95% match-level bootstrap intervals;
a day-cluster interval for Alcaraz minus IBM, supplied by the reconstruction over 14
tournament days, is [−0.1557, −0.0156].

**The two sub-samples differ, and the write-up says so.** The 29 archived rows carry the
gap: Alcaraz minus IBM -0.1735 [-0.2387, -0.1084]. The 36 evidenced live
2023 rows alone are inconclusive: -0.0138 [-0.1010, +0.0786], with log
loss 0.5646 (Alcaraz), 0.5249 (Pinnacle) and
0.5784 (IBM), and IBM picking more winners there (69.4% against
61.1%). The groups differ in site, year and round (the archived rows are mostly
third and fourth rounds; the live rows mostly first and second rounds of Wimbledon 2023),
so the pooled figure averages different kinds of matches. Adding the 178 undocumented rows
whose derived first-ball time would make them pre-match if uninterrupted gives
-0.0721 [-0.1093, -0.0348] on 234 matches; adding every undocumented row,
-0.0807 [-0.1144, -0.0472] on 266. The five files published during or
after play favour IBM (+0.0944 [-0.0134, +0.2039]), as in-play information should.

## Why IBM's number scores badly

IBM's likelihoods are hedged. On the 64, its favourite averages 61% and never exceeds
85%, against 68% for Alcaraz and 69% for Pinnacle. The three
systems pick nearly the same winners, so the accuracy gap is small; the log-loss gap is the
price of stating a 60% chance for matches the favourite wins three times in four. The
match-day rewrite does not explain the sub-sample difference: on the twelve matches with
both copies, IBM scores about the same either way.

## Limits

- Sixty-four matches, chosen by what happened to be archived or provable, not by design.
- IBM's product is a fan-facing likelihood, not a published forecasting benchmark, and it
  is revised through the day; the comparison holds only for copies that predate the match.
- Pinnacle's quote time is unknown, as everywhere in this repository. The 2022–2023 seasons
  are development data for Alcaraz; IBM's numbers were never an input to any model here.
- A full-draw comparison needs an immutable pre-match feed or IBM's own archive.

Evidence in the research archive: `data/raw/IBM01/` (archived and live captures, terms
read, first-play evidence with receipts), `experiments/IBM02.design.md`,
`references/IBM02/` (freeze, scorer, results, reconstruction). Source acknowledgement: the
Match Insights data are the work of IBM and the All England Lawn Tennis Club (Wimbledon)
and IBM and the USTA (US Open); archived copies via the Internet Archive.
