# Where the lead over public models comes from (WHY01), ATP 2017–2025

> **Exploratory, post-hoc, descriptive; ATP 2017–2025.** This page decomposes the saved
> forecasts of Alcaraz and every public model it was benchmarked against. No forecasting model
> was fitted. Segments and cut-points were chosen after the 2017–2024 aggregate results were
> known and are held at those values here. 2025 was inspected before the model freeze, so it
> is exposed retrospective data, not a holdout; the UTS and Ingram parts stay on 2024. Every
> number traces to [why01_2017_2025.json](why01_2017_2025.json), which holds the full tables
> (segment rows and aggregates only, no match rows). The analysis reruns in about a minute
> from the scripts kept in the research archive (`references/WHY01_EXT2025/`). The 2017–2024
> version stays as published: [WHY01_LEAD_DECOMPOSITION_2017_2024.md](WHY01_LEAD_DECOMPOSITION_2017_2024.md)
> and [why01.json](why01.json). Accepted as archive decision D139, independently reconstructed.

This version extends the WHY01 decomposition from 2017–2024 to 2017–2025 (EXT2025). It is
exploratory and post hoc. The 2025 season was inspected before the model freeze (D134) and has
been scored by REFIT2025, so it is exposed retrospective data, not a holdout. Segment definitions
and cut-points are held at the published 2017–2024 values; none was re-derived on the extended
rows. The UTS and Ingram parts, like every other 2024-cohort section, are still on ATP 2024
exactly as published. The 2017–2024 decomposition remains available as published in
`references/WHY01/`.

> **Exploratory, post-hoc, descriptive.** Saved forecasts on development data that the research
> process has already seen. No forecasting model was fitted for this analysis. Segments and
> cut-points were chosen after the 2017–2024 aggregate result was known. Intervals condition on
> the saved forecasts.

"Alcaraz" is `full_tier_entry`, the frozen model (ARMS01 attempt 002 Arm 1 for 2017–2024, its
REFIT2025 forecasts for 2025). Every difference is Alcaraz minus the rival (or later rung minus
earlier rung) in natural-log loss per match; negative favours Alcaraz. Intervals are 95%
match-level bootstrap percentiles (2,000 draws, seed 20260924); † marks n < 300. All numbers come
from [why01_2017_2025.json](why01_2017_2025.json); `why01_tables.py` renders the tables from it.

## Findings

**1. The lead is concentrated where a player's main-tour record is thin.** Against BuildOak
(−0.0067 [−0.0091, −0.0045] on 21,561 matches; calendar-week cluster interval [−0.0092, −0.0043]),
the three segments carrying the most gap beyond their size are the ones fixed from 2017–2024;
re-applying the top-three rule to 2017–2025 picks the same three:

- **a qualifier, lucky loser or wild card in the match**: n = 7,569 (35.1%), −0.0112 [−0.0156, −0.0068], 58.4% of the gap;
- **the lower-ranked player ranked 101–200**: n = 5,611 (26.0%), −0.0115 [−0.0164, −0.0061], 44.3% of the gap;
- **a player with fewer than 10 prior main-tour matches**: n = 2,655 (12.3%), −0.0151 [−0.0236, −0.0070], 27.5% of the gap.

They overlap heavily (1,130 matches are in all three) because they describe the same kind of
match: a qualifier ranked outside the top 100 with little tour-level history. Together they cover
44.0% of matches and 69.7% [52.5, 90.8] of the gap (−0.0107 [−0.0146, −0.0068]). Alcaraz still
leads in the other 56.0% (−0.0037 [−0.0065, −0.0009]). BuildOak is level in quarter-finals and
later (+0.0003 [−0.0050, +0.0056]; n = 3,791), in heavy-workload matches (+0.0017 [−0.0056,
+0.0092]), on grass (−0.0002 [−0.0068, +0.0069]) and in clear-favourite matches (−0.0034
[−0.0075, +0.0006]). Eleven of 36 segment-versus-rest contrasts exclude zero (two are mirror
pairs; the 2017–2024 report counted eight), against about 1.8 expected by chance, so the
concentration is more than noise. The exact count depends on the bootstrap seed: at least four
intervals end within about a tenth of a bootstrap standard deviation of zero (grass, a
lower-ranked player ranked 51–100 and clear favourites, which are counted, and a rank gap of 20
or less, which is not), and the independent reconstruction puts the count anywhere from eight to
twelve under another seed. Besides the
three segments above, they are the other side of the entry split, both sides of the workload
split, quarter-finals and later, 50–99 prior matches, grass, a lower-ranked player ranked 51–100
and clear favourites; in each of the last five the lead is smaller than in the rest. Which segment
"owns" the concentration cannot be identified, because the segments overlap.

The pattern repeats for every public rival (Table A2), although clay courts also enter the top
three against Kovalchik Elo (excess +9.5 points) and WElo (+9.9); against WElo the fewer-than-10
segment is fourth (+9.0). Against UTS and Ingram (2024, 2,681 matches), the fewer-than-10
segment (12.7% of matches) carries 36.0% and 35.3% of the gap (−0.0719 and −0.1283). Against the
four Elo baselines it carries 21.3% to 23.6% on 12.3% of matches. The ranking-only baseline is the
exception: its gap is flat across history bands (−0.0373 below 10 matches, −0.0352 at 100 or
more), because a ranking already reflects lower-tier results. It loses most in Grand Slams
(−0.0500) and clear-favourite matches (−0.0400).

**2. The lead is mostly discrimination, not calibration, except against Ingram.** Perfect in-sample
recalibration of each rival (a diagnostic counterfactual, not a forecast) bounds how much of its
gap is calibration (Table B2):

- **BuildOak** is overconfident (slope 0.883 [0.853, 0.915]). Recalibration removes 16.7% of the
  gap; −0.0056 [−0.0078, −0.0035] remains, and Alcaraz ranks matches better (AUC +0.0075 [+0.0049, +0.0103]).
- **UTS** (2024) is overconfident (slope 0.834). Recalibration removes 18.5% (19.2% against the
  published `full_tier` side); −0.0206 [−0.0279, −0.0122] remains (AUC +0.0260 [+0.0152, +0.0365]).
- **Ingram** (2024) is strongly overconfident (slope 0.619 [0.549, 0.695]; top-decile forecast
  0.928, observed 0.814). Recalibration removes 47.5% (48.5% against `full_tier`), but −0.0242
  [−0.0312, −0.0168] remains (AUC +0.0295 [+0.0203, +0.0392]).
- The five Elo/ranking baselines are well scaled (slopes 0.962 to 0.992). Recalibration removes
  1.8% to 9.5% of their gaps, mostly through the intercept. Player A is the lower ID and is the
  older player in 93.0% of matches, so their negative intercepts (−0.071 to −0.144) mean the
  ratings over-rate the older player. That is consistent with ratings lagging rising players.
  Alcaraz's intercept is −0.025.

**3. What Alcaraz knows that the rivals do not: lower-tier history first, entry status second.**
On the saved ladder over the same rows (Tables D1–D2), the rung before lower-tier history (P1)
is level with BuildOak: +0.0015 [−0.0005, +0.0036]. In thin-history matches P1 is behind BuildOak
(+0.0081 [+0.0011, +0.0153] below 10 matches; +0.0088 [+0.0029, +0.0147] after a long main-tour
absence). Adding qualifying, Challenger and Futures history (full_tier − P1) gains −0.0071
overall. The gain is −0.0220 [−0.0301, −0.0144] with a sub-10-match player, −0.0212 when the
lower-ranked player is outside the top 200, and about zero in quarter-finals and later (−0.0003
[−0.0034, +0.0027]); −0.0121 in the union of the three segments against −0.0031 elsewhere. This
block turns a tie with BuildOak into −0.0056 [−0.0079, −0.0033].

The entry-status block (−0.0012 [−0.0017, −0.0007]) concentrates in matches with a qualifier
(−0.0044 [−0.0065, −0.0023]), after a long absence (−0.0037) and at Grand Slams (−0.0024). It
does not concentrate in thin-history matches (−0.0011 [−0.0032, +0.0007]). It carries draw
information, not history. BuildOak's pinned ATP code drops entry columns and reads only main-tour
files from 1985 (Table E), so neither block has a counterpart in BuildOak. On 2024, even the plain
Elo rung beats Ingram (−0.0202 [−0.0316, −0.0082]) and ties UTS (+0.0006 [−0.0075, +0.0086]).
Ingram's deficit is largely its own overconfidence. The UTS deficit opens with the learned
combiner (P0 − UTS −0.0105 [−0.0175, −0.0035]) and widens with each block.

**4. When they disagree, Alcaraz wins slightly more often and loses less when wrong.** Alcaraz
and BuildOak pick different winners in 2,496 matches (11.6%). Alcaraz is right in 1,309 and
BuildOak in 1,187 (52.4% [50.4, 54.3]), at almost equal mean confidence (0.555 against 0.559).
These matches carry 35.2% [18.4, 53.6] of the gap. With a probability difference of 0.15 or more
(1,377 matches), Alcaraz is closer to the outcome 53.4% [50.6, 56.0] of the time, a small majority
whose interval only just excludes one half, and these matches carry 46.6% of the gap (−0.0492
[−0.0706, −0.0258]). BuildOak is the more confident side (0.654 against 0.636) and pays for it
when wrong. Large disagreements are over-represented in thin-history (ratio 2.01),
outside-top-200 (1.89) and long-absence (1.65) matches, and under-represented in quarter-finals
and later (0.83). Against UTS and Ingram (2024), disagreements carry more of the gap (74.5% and
68.1% for the large ones), and the rival is the more confident side (0.681 and 0.729 against 0.625
and 0.619). Against the Elo baselines, Alcaraz is the more confident side and is closer 66.7% to
69.0% of the time.

**5. The market is the mirror image.** Alcaraz trails Pinnacle by +0.0102 [+0.0081, +0.0123] on
21,361 priced matches. The market's edge is discrimination (AUC −0.0123 [−0.0148, −0.0098]);
recalibrating the market does not help. It concentrates after a long main-tour absence (+0.0197
[+0.0134, +0.0261]), in R128/R64 matches (+0.0141) and at Grand Slams (+0.0141). In thin-history
matches Alcaraz trails the market by about the average amount (+0.0112, excess +1.1 points):
lower-tier history lets it catch the public models there, not the market.

**Information sets.** Table E gives one sentence per rival. The fairness audit's common-input
control, where Alcaraz leads even on identical inputs (−0.0229 [−0.0325, −0.0140]), is a
**WTA 2024** result on 2,404 matches. The documents read contain no ATP common-input control. The
audit also notes that BuildOak's recipe was selected on ROC AUC, which rewards ordering and
ignores calibration. That is consistent with its overconfidence here (slope 0.883).

## What this does and does not show

- **Exploratory and post hoc.** The data are repeatedly exposed development seasons, and 2025 was
  inspected before the model freeze and scored by REFIT2025. The segments, cut-points (60 days,
  9 matches in 28 days, 10/25/50/100 prior matches, rank bands, Elo-margin terciles) and the
  top-three rule were fixed after the 2017–2024 aggregate results and after the README's
  qualifier screen, and are held at those values here. Because the Elo-margin cut-points are fixed,
  its three groups hold 7,178, 7,211 and 7,172 matches, not exact thirds. Nothing here is
  confirmatory, and no new model or feature is proposed or tested.
- **Accounting, not causation.** "Carries the gap" is an additive decomposition of fixed forecasts.
  The segments overlap, so their shares cannot be summed. Ladder increments compare separately
  selected and calibrated fits, so they mix feature effects with selection noise.
- **Uncertainty is understated.** Intervals are match-level and condition on saved forecasts.
  Calendar-week cluster intervals (304 ISO weeks) for every BuildOak segment are in [why01_2017_2025.json](why01_2017_2025.json)
  and are of similar width. No multiplicity correction is applied across 36 segments and nine rivals.
- **Measurement limits.** Thin history counts primary main-tour panel appearances from 2005 to D−2.
  Rest and workload are main-tour only, so a long "absence" mixes injury returns with players
  coming up from lower tiers. Wimbledon and the US Open 2022 carry no entry codes (245 targets,
  counted as none). Finals (118 matches) and other † cells are unstable.
- **BuildOak in 2025.** ATP 2025 is the first season in which BuildOak's frozen adapter switches on
  its recent-era model (EXT2025 amendment A1). That is a structural break in the rival inside the
  extended cohort.
- **Scope of the 2024 rows.** UTS and Ingram cover one season, 2024, and are not extended here.
  Their accepted comparisons used `full_tier`, which reproduces here (−0.0244 and −0.0452); tables
  use `full_tier_entry`, and [why01_2017_2025.json](why01_2017_2025.json) holds both. BuildOak's 2024-only gap straddles zero, so
  its 2024 share-of-gap figures are unbounded and not reported.
- **In-sample recalibration is not a forecast.** It fits two parameters on the outcomes it scores.
  It bounds the calibration component from above and says nothing about what a past-only fix would recover.

## Files and inputs

The extended run is `work/EXT2025/why01/ext2025_run/results.json`, made by the scripts in
`references/WHY01_EXT2025/` with the config `why01_ext2025_config.json` under the freeze
`references/EXT2025/FREEZE_SCORING_3_2026-09-24.json`. `why01_load.py` aligns the inputs and runs
the checks. `why01_analysis.py` does every computation and writes [why01_2017_2025.json](why01_2017_2025.json) and `INPUTS.tsv`.
`why01_tables.py` renders the Tables section. `why01_check_report.py` checks that every number
traces to [why01_2017_2025.json](why01_2017_2025.json). `INPUTS.tsv` lists the sha256 of all 99 files read. The config names
every input it adds or replaces: the REFIT2025 panel and features (all seasons), the REFIT2025 2025
labels and forecasts (Alcaraz, `full_tier`, P0 and the market), the EXT2025 P1 fit for 2025,
BuildOak's 2025 walk-forward forecasts, the 2017–2025 G-L baseline run (continuity configuration)
and the 21,561 all-target and 21,361 priced memberships. Every named input was found. Without the config the scripts reproduce
the published `references/WHY01/results.json` byte for byte. With it, the headline log losses equal
the EXT2025 BuildOak scoring pass and the 2017–2025 ladder to every printed digit, and every
2024-cohort section equals the published run.

## Tables

### A. Segment decomposition

**A1. Alcaraz − BuildOak by segment (21,561 ATP matches, 2017–2025).** Gap share = the segment's summed difference over the total; excess = gap share minus match share (percentage points); segment − rest = mean difference in the segment minus the rest. Italic rows overlap the entry split. † n < 300.

| Segment | n | Share | Alcaraz | BuildOak | Diff [95%] | Gap share | Excess share, pts [95%] | Segment − rest [95%] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all matches | 21,561 | 100.0% | 0.5991 | 0.6058 | −0.0067 [−0.0091, −0.0045] | 100.0% | +0.0 [+0.0, +0.0] | — |
| entry: Q, LL or WC involved | 7,569 | 35.1% | 0.6020 | 0.6132 | −0.0112 [−0.0156, −0.0068] | 58.4% | +23.3 [+6.8, +43.7] | −0.0069 [−0.0121, −0.0018] |
| entry: no Q, LL or WC | 13,992 | 64.9% | 0.5975 | 0.6019 | −0.0043 [−0.0071, −0.0017] | 41.6% | −23.3 [−43.7, −6.8] | +0.0069 [+0.0018, +0.0121] |
| level: Grand Slam | 4,361 | 20.2% | 0.5181 | 0.5246 | −0.0065 [−0.0120, −0.0014] | 19.4% | −0.8 [−15.5, +14.5] | +0.0003 [−0.0058, +0.0062] |
| level: Masters | 4,839 | 22.4% | 0.6147 | 0.6238 | −0.0091 [−0.0141, −0.0044] | 30.3% | +7.9 [−6.4, +24.3] | −0.0030 [−0.0087, +0.0023] |
| level: other tour (250/500) | 12,243 | 56.8% | 0.6214 | 0.6276 | −0.0061 [−0.0091, −0.0032] | 51.6% | −5.2 [−24.5, +11.7] | +0.0014 [−0.0031, +0.0063] |
| level: Finals † | 118 | 0.5% | 0.6328 | 0.6170 | +0.0158 [−0.0169, +0.0471] | −1.3% | −1.8 [−4.8, +0.8] | +0.0227 [−0.0097, +0.0539] |
| round: R128/R64 | 6,402 | 29.7% | 0.5786 | 0.5868 | −0.0082 [−0.0126, −0.0037] | 36.1% | +6.4 [−10.8, +25.1] | −0.0021 [−0.0073, +0.0032] |
| round: R32/R16 | 11,368 | 52.7% | 0.6037 | 0.6120 | −0.0083 [−0.0116, −0.0052] | 64.7% | +12.0 [−5.3, +32.2] | −0.0032 [−0.0081, +0.0015] |
| round: QF or later (incl. RR) | 3,791 | 17.6% | 0.6199 | 0.6196 | +0.0003 [−0.0050, +0.0056] | −0.7% | −18.3 [−35.3, −5.4] | +0.0085 [+0.0024, +0.0146] |
| surface: Hard | 12,578 | 58.3% | 0.5976 | 0.6046 | −0.0070 [−0.0102, −0.0040] | 60.5% | +2.2 [−16.2, +20.7] | −0.0006 [−0.0053, +0.0042] |
| surface: Clay | 6,476 | 30.0% | 0.6048 | 0.6136 | −0.0088 [−0.0133, −0.0045] | 39.2% | +9.2 [−7.4, +27.3] | −0.0029 [−0.0080, +0.0023] |
| surface: Grass | 2,507 | 11.6% | 0.5919 | 0.5921 | −0.0002 [−0.0068, +0.0069] | 0.3% | −11.4 [−25.5, −0.7] | +0.0075 [+0.0004, +0.0150] |
| lower-ranked player's rank: <=50 | 5,283 | 24.5% | 0.5948 | 0.5982 | −0.0034 [−0.0078, +0.0011] | 12.2% | −12.3 [−29.1, +2.5] | +0.0045 [−0.0008, +0.0098] |
| lower-ranked player's rank: 51-100 | 8,535 | 39.6% | 0.6092 | 0.6130 | −0.0038 [−0.0074, −0.0004] | 22.2% | −17.3 [−36.8, −0.4] | +0.0049 [+0.0001, +0.0097] |
| lower-ranked player's rank: 101-200 | 5,611 | 26.0% | 0.6071 | 0.6186 | −0.0115 [−0.0164, −0.0061] | 44.3% | +18.3 [+2.0, +37.9] | −0.0064 [−0.0120, −0.0006] |
| lower-ranked player's rank: >200 | 2,077 | 9.6% | 0.5528 | 0.5672 | −0.0144 [−0.0240, −0.0050] | 20.6% | +11.0 [−1.5, +24.6] | −0.0085 [−0.0180, +0.0013] |
| lower-ranked player's rank: unranked/missing † | 55 | 0.3% | 0.3632 | 0.3796 | −0.0165 [−0.0765, +0.0425] | 0.6% | +0.4 [−2.0, +2.7] | −0.0097 [−0.0696, +0.0494] |
| rank gap: <=20 | 5,922 | 27.5% | 0.6453 | 0.6486 | −0.0032 [−0.0074, +0.0009] | 13.2% | −14.3 [−31.8, +0.2] | +0.0048 [−0.0001, +0.0099] |
| rank gap: 21-50 | 6,846 | 31.8% | 0.6094 | 0.6169 | −0.0074 [−0.0113, −0.0037] | 35.1% | +3.3 [−12.8, +20.9] | −0.0010 [−0.0058, +0.0039] |
| rank gap: 51-100 | 5,048 | 23.4% | 0.5783 | 0.5861 | −0.0078 [−0.0127, −0.0029] | 27.2% | +3.8 [−11.8, +21.0] | −0.0014 [−0.0072, +0.0041] |
| rank gap: 101-200 | 2,447 | 11.3% | 0.5487 | 0.5570 | −0.0083 [−0.0158, −0.0011] | 14.0% | +2.7 [−9.0, +15.5] | −0.0018 [−0.0100, +0.0056] |
| rank gap: >200 | 1,243 | 5.8% | 0.5160 | 0.5276 | −0.0116 [−0.0246, +0.0013] | 9.9% | +4.1 [−7.1, +15.1] | −0.0051 [−0.0184, +0.0075] |
| rank gap: missing † | 55 | 0.3% | 0.3632 | 0.3796 | −0.0165 [−0.0765, +0.0425] | 0.6% | +0.4 [−2.0, +2.7] | −0.0097 [−0.0696, +0.0494] |
| Elo margin: close (lowest third of Elo margin) | 7,178 | 33.3% | 0.6653 | 0.6742 | −0.0088 [−0.0128, −0.0048] | 43.6% | +10.3 [−6.6, +30.9] | −0.0031 [−0.0082, +0.0020] |
| Elo margin: middle third | 7,211 | 33.4% | 0.6323 | 0.6403 | −0.0080 [−0.0124, −0.0037] | 39.7% | +6.3 [−12.1, +24.9] | −0.0019 [−0.0069, +0.0032] |
| Elo margin: clear favourite (top third) | 7,172 | 33.3% | 0.4993 | 0.5027 | −0.0034 [−0.0075, +0.0006] | 16.7% | −16.6 [−36.9, −0.5] | +0.0050 [+0.0002, +0.0099] |
| rest: either player >=60 days since last main-tour match | 3,235 | 15.0% | 0.5772 | 0.5863 | −0.0091 [−0.0162, −0.0021] | 20.1% | +5.1 [−9.6, +21.2] | −0.0027 [−0.0103, +0.0048] |
| rest: both <60 days | 18,326 | 85.0% | 0.6029 | 0.6093 | −0.0063 [−0.0088, −0.0039] | 79.9% | −5.1 [−21.2, +9.6] | +0.0027 [−0.0048, +0.0103] |
| workload: either player >=9 main-tour matches in prior 28 days | 1,820 | 8.4% | 0.5447 | 0.5430 | +0.0017 [−0.0056, +0.0092] | −2.1% | −10.5 [−21.4, −2.0] | +0.0092 [+0.0017, +0.0169] |
| workload: both <9 | 19,741 | 91.6% | 0.6041 | 0.6116 | −0.0075 [−0.0100, −0.0051] | 102.1% | +10.5 [+2.0, +21.4] | −0.0092 [−0.0169, −0.0017] |
| thin history: <10 prior main-tour matches | 2,655 | 12.3% | 0.5688 | 0.5839 | −0.0151 [−0.0236, −0.0070] | 27.5% | +15.2 [+2.1, +31.3] | −0.0095 [−0.0182, −0.0012] |
| thin history: 10-24 | 2,567 | 11.9% | 0.6123 | 0.6251 | −0.0128 [−0.0207, −0.0050] | 22.6% | +10.7 [−2.1, +25.2] | −0.0069 [−0.0151, +0.0014] |
| thin history: 25-49 | 3,361 | 15.6% | 0.6213 | 0.6297 | −0.0084 [−0.0147, −0.0026] | 19.4% | +3.8 [−8.8, +18.0] | −0.0020 [−0.0087, +0.0042] |
| thin history: 50-99 | 4,404 | 20.4% | 0.6083 | 0.6103 | −0.0019 [−0.0069, +0.0027] | 5.9% | −14.6 [−30.3, −1.3] | +0.0060 [+0.0005, +0.0114] |
| thin history: >=100 | 8,574 | 39.8% | 0.5911 | 0.5952 | −0.0042 [−0.0076, −0.0009] | 24.6% | −15.2 [−34.2, +1.8] | +0.0043 [−0.0005, +0.0090] |
| age: youngest player <=21 | 3,308 | 15.3% | 0.6006 | 0.6090 | −0.0084 [−0.0154, −0.0018] | 19.2% | +3.8 [−10.4, +18.0] | −0.0020 [−0.0091, +0.0048] |
| age: youngest >21 (or age missing) | 18,253 | 84.7% | 0.5988 | 0.6053 | −0.0064 [−0.0088, −0.0041] | 80.8% | −3.8 [−18.0, +10.4] | +0.0020 [−0.0048, +0.0091] |
| completion: retired or defaulted | 598 | 2.8% | 0.7057 | 0.7114 | −0.0057 [−0.0205, +0.0089] | 2.3% | −0.4 [−6.9, +5.9] | +0.0011 [−0.0143, +0.0159] |
| completion: completed | 20,963 | 97.2% | 0.5960 | 0.6028 | −0.0068 [−0.0091, −0.0045] | 97.7% | +0.4 [−5.9, +6.9] | −0.0011 [−0.0159, +0.0143] |
| *overlapping: Q involved* | 4,522 | 21.0% | 0.6044 | 0.6187 | −0.0143 [−0.0203, −0.0084] | 44.5% | +23.5 [+7.6, +42.7] | −0.0096 [−0.0158, −0.0030] |
| *overlapping: LL involved* | 1,073 | 5.0% | 0.6047 | 0.6071 | −0.0024 [−0.0139, +0.0093] | 1.8% | −3.2 [−12.6, +5.2] | +0.0046 [−0.0071, +0.0167] |
| *overlapping: WC involved* | 2,501 | 11.6% | 0.5996 | 0.6107 | −0.0111 [−0.0188, −0.0035] | 19.1% | +7.5 [−5.1, +21.0] | −0.0050 [−0.0132, +0.0032] |
| *overlapping: PR involved* | 446 | 2.1% | 0.6207 | 0.6243 | −0.0036 [−0.0221, +0.0150] | 1.1% | −1.0 [−7.3, +4.7] | +0.0032 [−0.0152, +0.0216] |
| *overlapping: exactly one side Q* | 4,303 | 20.0% | 0.6021 | 0.6163 | −0.0142 [−0.0203, −0.0081] | 41.9% | +22.0 [+6.4, +40.8] | −0.0093 [−0.0157, −0.0026] |

**A2. The three segments with the largest excess gap share, per rival** (partition segments with n ≥ 300; post hoc).

| Rival (matches) | Overall diff [95%] | Rank | Segment | n | Diff [95%] | Gap share | Excess, pts [95%] |
|---|---:|---:|---|---:|---:|---:|---:|
| BuildOak (21,561) | −0.0067 [−0.0091, −0.0045] | 1 | entry: Q, LL or WC involved | 7,569 | −0.0112 [−0.0156, −0.0068] | 58.4% | +23.3 [+6.8, +43.7] |
|  |  | 2 | lower-ranked player's rank: 101-200 | 5,611 | −0.0115 [−0.0164, −0.0061] | 44.3% | +18.3 [+2.0, +37.9] |
|  |  | 3 | thin history: <10 prior main-tour matches | 2,655 | −0.0151 [−0.0236, −0.0070] | 27.5% | +15.2 [+2.1, +31.3] |
| Pooled Elo K32 (21,561) | −0.0241 [−0.0270, −0.0212] | 1 | lower-ranked player's rank: >200 | 2,077 | −0.0576 [−0.0709, −0.0444] | 23.0% | +13.4 [+8.7, +18.2] |
|  |  | 2 | rest: either player >=60 days since last main-tour match | 3,235 | −0.0443 [−0.0536, −0.0346] | 27.6% | +12.5 [+7.4, +17.8] |
|  |  | 3 | thin history: <10 prior main-tour matches | 2,655 | −0.0458 [−0.0566, −0.0352] | 23.4% | +11.1 [+6.1, +15.9] |
| Ranking logistic (21,561) | −0.0344 [−0.0379, −0.0311] | 1 | level: Grand Slam | 4,361 | −0.0500 [−0.0579, −0.0424] | 29.4% | +9.2 [+5.1, +13.4] |
|  |  | 2 | Elo margin: clear favourite (top third) | 7,172 | −0.0400 [−0.0457, −0.0341] | 38.7% | +5.4 [+0.8, +10.0] |
|  |  | 3 | round: R128/R64 | 6,402 | −0.0400 [−0.0469, −0.0336] | 34.5% | +4.8 [+0.2, +9.5] |
| Kovalchik Elo (21,561) | −0.0281 [−0.0311, −0.0250] | 1 | rest: either player >=60 days since last main-tour match | 3,235 | −0.0481 [−0.0579, −0.0386] | 25.7% | +10.7 [+6.2, +15.3] |
|  |  | 2 | thin history: <10 prior main-tour matches | 2,655 | −0.0500 [−0.0609, −0.0392] | 21.9% | +9.6 [+5.2, +14.0] |
|  |  | 3 | surface: Clay | 6,476 | −0.0370 [−0.0428, −0.0312] | 39.6% | +9.5 [+4.6, +14.6] |
| FiveThirtyEight surface Elo (21,561) | −0.0247 [−0.0275, −0.0218] | 1 | rest: either player >=60 days since last main-tour match | 3,235 | −0.0447 [−0.0542, −0.0355] | 27.2% | +12.2 [+7.2, +17.3] |
|  |  | 2 | entry: Q, LL or WC involved | 7,569 | −0.0328 [−0.0385, −0.0270] | 46.6% | +11.5 [+5.9, +17.1] |
|  |  | 3 | thin history: <10 prior main-tour matches | 2,655 | −0.0474 [−0.0584, −0.0370] | 23.6% | +11.3 [+6.6, +16.0] |
| WElo (21,561) | −0.0274 [−0.0304, −0.0242] | 1 | rest: either player >=60 days since last main-tour match | 3,235 | −0.0472 [−0.0570, −0.0371] | 25.9% | +10.9 [+6.1, +15.6] |
|  |  | 2 | lower-ranked player's rank: >200 | 2,077 | −0.0562 [−0.0693, −0.0431] | 19.8% | +10.2 [+6.1, +14.3] |
|  |  | 3 | surface: Clay | 6,476 | −0.0364 [−0.0423, −0.0305] | 39.9% | +9.9 [+4.8, +15.2] |
| UTS formula (2024) (2,681) | −0.0253 [−0.0339, −0.0158] | 1 | entry: Q, LL or WC involved | 968 | −0.0428 [−0.0625, −0.0241] | 61.0% | +24.9 [+6.6, +43.8] |
|  |  | 2 | thin history: <10 prior main-tour matches | 340 | −0.0719 [−0.1138, −0.0307] | 36.0% | +23.4 [+5.6, +41.6] |
|  |  | 3 | lower-ranked player's rank: 101-200 | 677 | −0.0336 [−0.0558, −0.0115] | 33.5% | +8.3 [−11.1, +26.1] |
| Ingram point model (2024) (2,681) | −0.0461 [−0.0580, −0.0349] | 1 | thin history: <10 prior main-tour matches | 340 | −0.1283 [−0.1839, −0.0763] | 35.3% | +22.6 [+11.1, +34.6] |
|  |  | 2 | entry: Q, LL or WC involved | 968 | −0.0724 [−0.0974, −0.0484] | 56.6% | +20.5 [+7.8, +33.3] |
|  |  | 3 | lower-ranked player's rank: 101-200 | 677 | −0.0649 [−0.0939, −0.0376] | 35.5% | +10.2 [−2.3, +23.0] |
| Pinnacle (market, reference) (21,361) | +0.0102 [+0.0081, +0.0123] | 1 | rest: either player >=60 days since last main-tour match | 3,180 | +0.0197 [+0.0134, +0.0261] | 28.6% | +13.7 [+5.7, +22.9] |
|  |  | 2 | round: R128/R64 | 6,334 | +0.0141 [+0.0101, +0.0183] | 40.8% | +11.2 [+1.3, +21.6] |
|  |  | 3 | level: Grand Slam | 4,339 | +0.0141 [+0.0091, +0.0195] | 28.1% | +7.8 [−1.0, +16.9] |

**A3. Union of BuildOak's top three and the rest** (week-cluster = calendar-week cluster bootstrap sensitivity).

| BuildOak top three | n | Share | Alcaraz | BuildOak | Diff [95%] | Week-cluster [95%] | Gap share [95%] |
|---|---:|---:|---:|---:|---:|---:|---:|
| union of the three | 9,493 | 44.0% | 0.5993 | 0.6100 | −0.0107 [−0.0146, −0.0068] | [−0.0146, −0.0063] | 69.7% [+52.5, +90.8] |
| none of the three | 12,068 | 56.0% | 0.5989 | 0.6025 | −0.0037 [−0.0065, −0.0009] | [−0.0067, −0.0008] | 30.3% [+9.2, +47.5] |

Overlap counts: entry: Q, LL or WC involved & lower_ranked_player_rank: 101-200: 3,811; entry: Q, LL or WC involved & thin_history: <10 prior main-tour matches: 2,308; lower-ranked player's rank: 101-200 & thin_history: <10 prior main-tour matches: 1,353; all three: 1,130.

**A4. UTS and Ingram, ATP 2024 (2,681 matches), selected segments.**

| Segment (ATP 2024) | n | UTS diff [95%] | UTS gap share | Ingram diff [95%] | Ingram gap share |
|---|---:|---:|---:|---:|---:|
| all matches | 2,681 | −0.0253 [−0.0339, −0.0158] | 100.0% | −0.0461 [−0.0580, −0.0349] | 100.0% |
| entry: Q, LL or WC involved | 968 | −0.0428 [−0.0625, −0.0241] | 61.0% | −0.0724 [−0.0974, −0.0484] | 56.6% |
| entry: no Q, LL or WC | 1,713 | −0.0154 [−0.0241, −0.0064] | 39.0% | −0.0313 [−0.0438, −0.0199] | 43.4% |
| thin history: <10 prior main-tour matches | 340 | −0.0719 [−0.1138, −0.0307] | 36.0% | −0.1283 [−0.1839, −0.0763] | 35.3% |
| thin history: 10-24 | 307 | −0.0353 [−0.0637, −0.0058] | 15.9% | −0.0648 [−0.1064, −0.0240] | 16.1% |
| thin history: 25-49 | 428 | −0.0170 [−0.0366, +0.0031] | 10.7% | −0.0322 [−0.0564, −0.0079] | 11.1% |
| thin history: 50-99 | 664 | −0.0202 [−0.0348, −0.0046] | 19.8% | −0.0368 [−0.0582, −0.0176] | 19.8% |
| thin history: >=100 | 942 | −0.0126 [−0.0243, −0.0013] | 17.5% | −0.0233 [−0.0381, −0.0090] | 17.8% |
| lower-ranked player's rank: <=50 | 676 | −0.0130 [−0.0258, +0.0001] | 12.9% | −0.0310 [−0.0500, −0.0138] | 16.9% |
| lower-ranked player's rank: 51-100 | 1,045 | −0.0220 [−0.0337, −0.0105] | 33.9% | −0.0362 [−0.0545, −0.0190] | 30.6% |
| lower-ranked player's rank: 101-200 | 677 | −0.0336 [−0.0558, −0.0115] | 33.5% | −0.0649 [−0.0939, −0.0376] | 35.5% |
| lower-ranked player's rank: >200 † | 280 | −0.0482 [−0.0911, −0.0079] | 19.9% | −0.0716 [−0.1153, −0.0307] | 16.2% |
| round: R128/R64 | 847 | −0.0318 [−0.0491, −0.0160] | 39.7% | −0.0481 [−0.0680, −0.0294] | 32.9% |
| round: R32/R16 | 1,379 | −0.0222 [−0.0343, −0.0096] | 45.1% | −0.0454 [−0.0621, −0.0290] | 50.7% |
| round: QF or later (incl. RR) | 455 | −0.0227 [−0.0430, −0.0033] | 15.2% | −0.0447 [−0.0746, −0.0170] | 16.4% |
| rest: either player >=60 days since last main-tour match | 355 | −0.0372 [−0.0691, −0.0069] | 19.5% | −0.0657 [−0.1004, −0.0314] | 18.8% |
| level: Grand Slam | 505 | −0.0309 [−0.0529, −0.0093] | 23.0% | −0.0556 [−0.0851, −0.0296] | 22.7% |

**A5. Five Elo/ranking baselines, Alcaraz − baseline by segment** (21,561; intervals in results.json).

| Segment | n | Pooled K32 | Rank logistic | Kovalchik | FiveThirtyEight | WElo |
|---|---:|---:|---:|---:|---:|---:|
| all matches | 21,561 | −0.0241 | −0.0344 | −0.0281 | −0.0247 | −0.0274 |
| entry: Q, LL or WC involved | 7,569 | −0.0308 | −0.0341 | −0.0349 | −0.0328 | −0.0343 |
| entry: no Q, LL or WC | 13,992 | −0.0205 | −0.0346 | −0.0244 | −0.0203 | −0.0236 |
| thin history: <10 prior main-tour matches | 2,655 | −0.0458 | −0.0373 | −0.0500 | −0.0474 | −0.0473 |
| thin history: 10-24 | 2,567 | −0.0273 | −0.0309 | −0.0349 | −0.0315 | −0.0306 |
| thin history: 25-49 | 3,361 | −0.0289 | −0.0334 | −0.0294 | −0.0275 | −0.0328 |
| thin history: 50-99 | 4,404 | −0.0191 | −0.0339 | −0.0235 | −0.0188 | −0.0230 |
| thin history: >=100 | 8,574 | −0.0172 | −0.0352 | −0.0212 | −0.0176 | −0.0203 |
| lower-ranked player's rank: <=50 | 5,283 | −0.0144 | −0.0331 | −0.0199 | −0.0142 | −0.0177 |
| lower-ranked player's rank: 51-100 | 8,535 | −0.0204 | −0.0306 | −0.0235 | −0.0204 | −0.0237 |
| lower-ranked player's rank: 101-200 | 5,611 | −0.0245 | −0.0325 | −0.0333 | −0.0310 | −0.0298 |
| lower-ranked player's rank: >200 | 2,077 | −0.0576 | −0.0506 | −0.0502 | −0.0483 | −0.0562 |
| round: R128/R64 | 6,402 | −0.0287 | −0.0400 | −0.0357 | −0.0305 | −0.0350 |
| round: R32/R16 | 11,368 | −0.0256 | −0.0337 | −0.0296 | −0.0269 | −0.0281 |
| round: QF or later (incl. RR) | 3,791 | −0.0119 | −0.0271 | −0.0108 | −0.0082 | −0.0123 |
| rest: either player >=60 days since last main-tour match | 3,235 | −0.0443 | −0.0376 | −0.0481 | −0.0447 | −0.0472 |
| level: Grand Slam | 4,361 | −0.0322 | −0.0500 | −0.0408 | −0.0340 | −0.0381 |
| Elo margin: clear favourite (top third) | 7,172 | −0.0206 | −0.0400 | −0.0242 | −0.0211 | −0.0236 |

### B. Calibration and discrimination

**B1. Per-system scores.** Recal = in-sample logistic regression of the outcome on logit(p); slope below 1 = overconfident. Reliability and resolution use deciles of each system's own forecast.

| System | Cohort | Log loss | Recal slope [95%] | Intercept | LL after recal | AUC [95%] | Brier | Reliability | Resolution |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Alcaraz (full_tier_entry) | 21,561 | 0.5991 | 0.990 [0.956, 1.026] | −0.025 | 0.5990 | 0.7370 [0.7303, 0.7434] | 0.2070 | 0.00022 | 0.04259 |
| full_tier (previous version) | 21,561 | 0.6003 | 0.988 [0.954, 1.024] | −0.024 | 0.6002 | 0.7354 [0.7289, 0.7419] | 0.2075 | 0.00023 | 0.04185 |
| BuildOak | 21,561 | 0.6058 | 0.883 [0.853, 0.915] | −0.009 | 0.6047 | 0.7294 [0.7229, 0.7361] | 0.2099 | 0.00058 | 0.03924 |
| Pooled Elo K32 | 21,561 | 0.6232 | 0.992 [0.954, 1.032] | −0.144 | 0.6209 | 0.7092 [0.7024, 0.7160] | 0.2173 | 0.00111 | 0.03287 |
| Ranking logistic | 21,561 | 0.6335 | 0.976 [0.935, 1.019] | −0.071 | 0.6329 | 0.6917 [0.6848, 0.6986] | 0.2219 | 0.00065 | 0.02820 |
| Kovalchik Elo | 21,561 | 0.6272 | 0.962 [0.925, 1.000] | −0.104 | 0.6259 | 0.7031 [0.6962, 0.7096] | 0.2190 | 0.00074 | 0.03094 |
| FiveThirtyEight surface Elo | 21,561 | 0.6238 | 0.966 [0.929, 1.004] | −0.121 | 0.6220 | 0.7083 [0.7015, 0.7150] | 0.2175 | 0.00093 | 0.03262 |
| WElo | 21,561 | 0.6264 | 0.972 [0.935, 1.013] | −0.139 | 0.6242 | 0.7050 [0.6982, 0.7116] | 0.2187 | 0.00116 | 0.03157 |
| Elo rung | 21,561 | 0.6245 | 0.881 [0.847, 0.915] | −0.144 | 0.6208 | 0.7091 [0.7021, 0.7158] | 0.2177 | 0.00158 | 0.03295 |
| P0 rung | 21,561 | 0.6139 | 0.999 [0.964, 1.038] | −0.131 | 0.6120 | 0.7204 [0.7137, 0.7270] | 0.2134 | 0.00101 | 0.03650 |
| P1 rung | 21,561 | 0.6073 | 0.977 [0.943, 1.013] | −0.031 | 0.6072 | 0.7275 [0.7211, 0.7341] | 0.2104 | 0.00020 | 0.03914 |
| Alcaraz (full_tier_entry) | 21,361 priced | 0.5993 | 0.992 [0.958, 1.028] | −0.025 | 0.5992 | 0.7367 [0.7302, 0.7432] | 0.2071 | 0.00025 | 0.04250 |
| Pinnacle (market, reference) | 21,361 priced | 0.5890 | 1.020 [0.986, 1.054] | −0.040 | 0.5888 | 0.7489 [0.7427, 0.7554] | 0.2028 | 0.00029 | 0.04650 |
| Alcaraz (full_tier_entry) | 2,681 (2024) | 0.5956 | 1.007 [0.912, 1.113] | −0.013 | 0.5955 | 0.7390 [0.7206, 0.7578] | 0.2057 | 0.00091 | 0.04440 |
| full_tier (previous version) | 2,681 (2024) | 0.5965 | 1.012 [0.915, 1.118] | −0.014 | 0.5965 | 0.7379 [0.7196, 0.7566] | 0.2062 | 0.00089 | 0.04319 |
| BuildOak | 2,681 (2024) | 0.6000 | 0.947 [0.852, 1.047] | +0.020 | 0.5998 | 0.7342 [0.7154, 0.7530] | 0.2077 | 0.00107 | 0.04185 |
| UTS formula | 2,681 (2024) | 0.6209 | 0.834 [0.746, 0.926] | −0.132 | 0.6162 | 0.7131 [0.6933, 0.7323] | 0.2164 | 0.00344 | 0.03624 |
| Ingram point model | 2,681 (2024) | 0.6417 | 0.619 [0.549, 0.695] | −0.131 | 0.6198 | 0.7096 [0.6904, 0.7287] | 0.2222 | 0.00679 | 0.03365 |

**B2. Share of each gap an in-sample recalibration of the rival would remove** (upper bound on the calibration component; diagnostic counterfactual, not a forecast).

| Alcaraz minus … | Cohort | Raw gap [95%] | vs rival recalibrated in-sample [95%] | Share of gap removed | Both recalibrated [95%] | AUC, Alcaraz − rival [95%] |
|---|---|---:|---:|---:|---:|---:|
| BuildOak | 21,561 | −0.0067 [−0.0091, −0.0045] | −0.0056 [−0.0078, −0.0035] | 16.7% | −0.0057 [−0.0079, −0.0036] | +0.0075 [+0.0049, +0.0103] |
| Pooled Elo K32 | 21,561 | −0.0241 [−0.0270, −0.0212] | −0.0218 [−0.0246, −0.0190] | 9.5% | −0.0219 [−0.0247, −0.0192] | +0.0277 [+0.0242, +0.0314] |
| Ranking logistic | 21,561 | −0.0344 [−0.0379, −0.0311] | −0.0338 [−0.0371, −0.0305] | 1.8% | −0.0339 [−0.0372, −0.0307] | +0.0453 [+0.0407, +0.0499] |
| Kovalchik Elo | 21,561 | −0.0281 [−0.0311, −0.0250] | −0.0268 [−0.0296, −0.0236] | 4.7% | −0.0268 [−0.0298, −0.0238] | +0.0339 [+0.0300, +0.0380] |
| FiveThirtyEight surface Elo | 21,561 | −0.0247 [−0.0275, −0.0218] | −0.0230 [−0.0257, −0.0200] | 7.1% | −0.0230 [−0.0258, −0.0202] | +0.0287 [+0.0250, +0.0324] |
| WElo | 21,561 | −0.0274 [−0.0304, −0.0242] | −0.0251 [−0.0280, −0.0221] | 8.2% | −0.0252 [−0.0282, −0.0222] | +0.0320 [+0.0281, +0.0361] |
| Pinnacle (market, reference) | 21,361 | +0.0102 [+0.0081, +0.0123] | +0.0104 [+0.0083, +0.0126] | −1.9% | +0.0104 [+0.0082, +0.0124] | −0.0123 [−0.0148, −0.0098] |
| BuildOak | 2,681 | −0.0045 [−0.0108, +0.0017] | −0.0042 [−0.0099, +0.0021] | 5.9% | −0.0042 [−0.0106, +0.0016] | +0.0049 [−0.0030, +0.0127] |
| UTS formula | 2,681 | −0.0253 [−0.0339, −0.0158] | −0.0206 [−0.0279, −0.0122] | 18.5% | −0.0206 [−0.0286, −0.0127] | +0.0260 [+0.0152, +0.0365] |
| Ingram point model | 2,681 | −0.0461 [−0.0580, −0.0349] | −0.0242 [−0.0312, −0.0168] | 47.5% | −0.0242 [−0.0317, −0.0173] | +0.0295 [+0.0203, +0.0392] |
| UTS formula | 2,681, full_tier side | −0.0244 [−0.0330, −0.0151] | −0.0197 [−0.0269, −0.0112] | 19.2% | −0.0197 [−0.0277, −0.0118] | +0.0248 [+0.0141, +0.0350] |
| Ingram point model | 2,681, full_tier side | −0.0452 [−0.0569, −0.0341] | −0.0233 [−0.0300, −0.0161] | 48.5% | −0.0233 [−0.0305, −0.0166] | +0.0283 [+0.0194, +0.0376] |

**B3. Reliability by forecast decile.**

| Decile | Alcaraz 21,561: mean p / observed | BuildOak 21,561: mean p / observed | Alcaraz 2024: mean p / observed | UTS 2024: mean p / observed | Ingram 2024: mean p / observed |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.161 / 0.158 | 0.139 / 0.166 | 0.152 / 0.119 | 0.160 / 0.160 | 0.106 / 0.164 |
| 2 | 0.276 / 0.269 | 0.254 / 0.278 | 0.278 / 0.254 | 0.285 / 0.261 | 0.243 / 0.299 |
| 3 | 0.342 / 0.344 | 0.330 / 0.362 | 0.344 / 0.381 | 0.366 / 0.354 | 0.337 / 0.366 |
| 4 | 0.402 / 0.419 | 0.397 / 0.418 | 0.400 / 0.463 | 0.432 / 0.493 | 0.421 / 0.474 |
| 5 | 0.463 / 0.469 | 0.461 / 0.458 | 0.457 / 0.455 | 0.500 / 0.489 | 0.502 / 0.433 |
| 6 | 0.523 / 0.489 | 0.526 / 0.507 | 0.514 / 0.474 | 0.562 / 0.515 | 0.576 / 0.506 |
| 7 | 0.588 / 0.564 | 0.593 / 0.557 | 0.577 / 0.567 | 0.621 / 0.595 | 0.654 / 0.575 |
| 8 | 0.660 / 0.648 | 0.665 / 0.644 | 0.649 / 0.627 | 0.693 / 0.562 | 0.738 / 0.644 |
| 9 | 0.745 / 0.750 | 0.752 / 0.737 | 0.744 / 0.750 | 0.775 / 0.679 | 0.827 / 0.687 |
| 10 | 0.869 / 0.867 | 0.877 / 0.852 | 0.871 / 0.870 | 0.880 / 0.851 | 0.928 / 0.814 |

Decile sizes: 2,155–2,157 (21,561) and about 268 (2,681).

### C. Disagreements

**C1. Different picks (forecasts on opposite sides of 0.5), then probability gaps of 0.15 or more.**

| Rival | Different picks (share) | Alcaraz right / rival right | Alcaraz right share [95%] | Mean confidence A / R | Diff [95%] | Share of total gap [95%] |
|---|---:|---:|---:|---:|---:|---:|
| BuildOak | 2,496 (11.6%) | 1,309 / 1,187 | 52.4% [50.4, 54.3] | 0.555 / 0.559 | −0.0205 [−0.0305, −0.0100] | 35.2% [+18.4, +53.6] |
| Pooled Elo K32 | 3,442 (16.0%) | 1,962 / 1,480 | 57.0% [55.4, 58.6] | 0.573 / 0.557 | −0.0463 [−0.0562, −0.0365] | 30.7% [+25.3, +36.3] |
| Ranking logistic | 4,320 (20.0%) | 2,506 / 1,814 | 58.0% [56.6, 59.5] | 0.588 / 0.568 | −0.0629 [−0.0736, −0.0521] | 36.7% [+31.6, +41.6] |
| Kovalchik Elo | 3,698 (17.2%) | 2,113 / 1,585 | 57.1% [55.6, 58.8] | 0.576 / 0.568 | −0.0606 [−0.0719, −0.0501] | 37.0% [+31.8, +42.4] |
| FiveThirtyEight surface Elo | 3,358 (15.6%) | 1,901 / 1,457 | 56.6% [55.0, 58.3] | 0.571 / 0.566 | −0.0554 [−0.0663, −0.0449] | 34.9% [+29.4, +40.5] |
| WElo | 3,773 (17.5%) | 2,143 / 1,630 | 56.8% [55.3, 58.4] | 0.578 / 0.567 | −0.0579 [−0.0690, −0.0475] | 37.0% [+31.7, +42.4] |
| UTS formula (2024) | 425 (15.9%) | 242 / 183 | 56.9% [52.1, 61.5] | 0.571 / 0.585 | −0.0891 [−0.1259, −0.0522] | 55.8% [+38.0, +77.3] |
| Ingram point model (2024) | 391 (14.6%) | 240 / 151 | 61.4% [56.8, 66.2] | 0.567 / 0.588 | −0.1000 [−0.1383, −0.0627] | 31.6% [+21.0, +43.5] |
| Pinnacle (market, reference) | 2,220 (10.4%) | 966 / 1,254 | 43.5% [41.4, 45.5] | 0.550 / 0.558 | +0.0316 [+0.0216, +0.0424] | 32.1% [+23.4, +41.8] |

| Rival | Probability gap ≥ 0.15 (share) | Alcaraz closer to outcome [95%] | Mean confidence A / R | Alcaraz LL / rival LL | Diff [95%] | Share of total gap [95%] |
|---|---:|---:|---:|---:|---:|---:|
| BuildOak | 1,377 (6.4%) | 735 = 53.4% [50.6, 56.0] | 0.636 / 0.654 | 0.6507 / 0.6999 | −0.0492 [−0.0706, −0.0258] | 46.6% [+28.7, +65.3] |
| Pooled Elo K32 | 2,634 (12.2%) | 1,817 = 69.0% [67.2, 70.8] | 0.699 / 0.610 | 0.5751 / 0.6811 | −0.1060 [−0.1220, −0.0898] | 53.7% [+48.1, +59.7] |
| Ranking logistic | 4,421 (20.5%) | 3,042 = 68.8% [67.5, 70.1] | 0.702 / 0.615 | 0.5720 / 0.6828 | −0.1108 [−0.1238, −0.0977] | 66.0% [+61.3, +70.5] |
| Kovalchik Elo | 3,176 (14.7%) | 2,123 = 66.8% [65.2, 68.5] | 0.682 / 0.630 | 0.5840 / 0.6964 | −0.1124 [−0.1282, −0.0972] | 58.9% [+53.6, +64.4] |
| FiveThirtyEight surface Elo | 2,663 (12.4%) | 1,776 = 66.7% [64.9, 68.5] | 0.676 / 0.632 | 0.5875 / 0.7006 | −0.1131 [−0.1295, −0.0969] | 56.5% [+51.0, +62.3] |
| WElo | 3,257 (15.1%) | 2,196 = 67.4% [65.8, 69.1] | 0.684 / 0.622 | 0.5797 / 0.6925 | −0.1128 [−0.1277, −0.0977] | 62.3% [+56.7, +68.1] |
| UTS formula (2024) | 370 (13.8%) | 215 = 58.1% [53.2, 63.0] | 0.625 / 0.681 | 0.6221 / 0.7588 | −0.1367 [−0.1854, −0.0871] | 74.5% [+57.1, +95.6] |
| Ingram point model (2024) | 459 (17.1%) | 248 = 54.0% [49.6, 58.5] | 0.619 / 0.729 | 0.6502 / 0.8338 | −0.1836 [−0.2366, −0.1313] | 68.1% [+56.3, +80.6] |
| Pinnacle (market, reference) | 898 (4.2%) | 349 = 38.9% [35.6, 42.1] | 0.627 / 0.655 | 0.7015 / 0.6246 | +0.0769 [+0.0506, +0.1038] | 31.6% [+22.6, +41.2] |

**C2. Over-representation among probability gaps ≥ 0.15** (share of the set over share of all matches).

| Segment | BuildOak: n in set, ratio | UTS 2024: n, ratio | Ingram 2024: n, ratio |
|---|---:|---:|---:|
| entry: Q, LL or WC involved | 717, 1.48 | 204, 1.53 † | 259, 1.56 † |
| thin history: <10 prior main-tour matches | 341, 2.01 | 109, 2.32 † | 118, 2.03 † |
| thin history: 10-24 | 231, 1.41 † | 59, 1.39 † | 95, 1.81 † |
| lower-ranked player's rank: >200 | 251, 1.89 † | 78, 2.02 † | 66, 1.38 † |
| lower-ranked player's rank: 101-200 | 473, 1.32 | 134, 1.43 † | 163, 1.41 † |
| rest: either player >=60 days since last main-tour match | 340, 1.65 | 77, 1.57 † | 84, 1.38 † |
| round: QF or later (incl. RR) | 200, 0.83 † | 41, 0.65 † | 70, 0.90 † |
| Elo margin: close (lowest third of Elo margin) | 581, 1.27 | 149, 1.21 † | 173, 1.13 † |

### D. Which block earns the lead where

**D1. Ladder increments by segment (later rung − earlier rung, 21,561 matches).**

| Segment | n | P0 − Elo [95%] | P1 − P0 [95%] | full_tier − P1 (lower tiers) [95%] | entry block [95%] |
|---|---:|---:|---:|---:|---:|
| all matches | 21,561 | −0.0107 [−0.0129, −0.0086] | −0.0065 [−0.0082, −0.0049] | −0.0071 [−0.0088, −0.0054] | −0.0012 [−0.0017, −0.0007] |
| union of BuildOak top three | 9,493 | −0.0150 [−0.0190, −0.0114] | −0.0042 [−0.0067, −0.0016] | −0.0121 [−0.0152, −0.0091] | −0.0024 [−0.0035, −0.0013] |
| none of BuildOak top three | 12,068 | −0.0072 [−0.0098, −0.0048] | −0.0084 [−0.0105, −0.0063] | −0.0031 [−0.0048, −0.0014] | −0.0003 [−0.0006, +0.0001] |
| entry: Q, LL or WC involved | 7,569 | −0.0148 [−0.0192, −0.0107] | −0.0030 [−0.0058, +0.0000] | −0.0128 [−0.0162, −0.0093] | −0.0027 [−0.0040, −0.0014] |
| entry: no Q, LL or WC | 13,992 | −0.0084 [−0.0107, −0.0062] | −0.0084 [−0.0104, −0.0065] | −0.0040 [−0.0057, −0.0023] | −0.0004 [−0.0007, +0.0000] |
| overlapping: Q involved | 4,522 | −0.0090 [−0.0144, −0.0041] | −0.0029 [−0.0064, +0.0008] | −0.0135 [−0.0181, −0.0091] | −0.0044 [−0.0065, −0.0023] |
| thin history: <10 prior main-tour matches | 2,655 | −0.0196 [−0.0281, −0.0112] | −0.0019 [−0.0069, +0.0030] | −0.0220 [−0.0301, −0.0144] | −0.0011 [−0.0032, +0.0007] |
| thin history: 10-24 | 2,567 | −0.0117 [−0.0184, −0.0053] | −0.0073 [−0.0125, −0.0021] | −0.0105 [−0.0160, −0.0048] | −0.0017 [−0.0035, +0.0004] |
| thin history: >=100 | 8,574 | −0.0071 [−0.0102, −0.0042] | −0.0060 [−0.0086, −0.0038] | −0.0032 [−0.0049, −0.0012] | −0.0009 [−0.0016, −0.0002] |
| lower-ranked player's rank: 101-200 | 5,611 | −0.0085 [−0.0129, −0.0044] | −0.0052 [−0.0086, −0.0019] | −0.0099 [−0.0138, −0.0059] | −0.0030 [−0.0045, −0.0017] |
| lower-ranked player's rank: >200 | 2,077 | −0.0292 [−0.0398, −0.0184] | −0.0037 [−0.0094, +0.0021] | −0.0212 [−0.0290, −0.0133] | −0.0026 [−0.0049, −0.0006] |
| rest: either player >=60 days since last main-tour match | 3,235 | −0.0231 [−0.0310, −0.0163] | −0.0023 [−0.0066, +0.0020] | −0.0141 [−0.0201, −0.0081] | −0.0037 [−0.0055, −0.0019] |
| round: QF or later (incl. RR) | 3,791 | −0.0075 [−0.0121, −0.0031] | −0.0072 [−0.0110, −0.0034] | −0.0003 [−0.0034, +0.0027] | −0.0000 [−0.0011, +0.0011] |
| workload: either player >=9 main-tour matches in prior 28 days | 1,820 | −0.0028 [−0.0089, +0.0027] | −0.0073 [−0.0122, −0.0028] | −0.0035 [−0.0071, +0.0001] | −0.0008 [−0.0020, +0.0006] |
| level: Grand Slam | 4,361 | −0.0094 [−0.0137, −0.0050] | −0.0083 [−0.0119, −0.0048] | −0.0073 [−0.0110, −0.0036] | −0.0024 [−0.0033, −0.0015] |

**D2. Each rung minus BuildOak (21,561), and each rung minus the 2024 rivals (2,681).**

| Segment | Elo − BO | P0 − BO | P1 − BO [95%] | full_tier − BO [95%] | Alcaraz − BO [95%] |
|---|---:|---:|---:|---:|---:|
| all matches | +0.0187 | +0.0080 | +0.0015 [−0.0005, +0.0036] | −0.0056 [−0.0079, −0.0033] | −0.0067 [−0.0091, −0.0045] |
| union of BuildOak top three | +0.0230 | +0.0080 | +0.0038 [+0.0003, +0.0071] | −0.0083 [−0.0121, −0.0046] | −0.0107 [−0.0146, −0.0068] |
| none of BuildOak top three | +0.0153 | +0.0081 | −0.0003 [−0.0031, +0.0022] | −0.0034 [−0.0063, −0.0007] | −0.0037 [−0.0065, −0.0009] |
| entry: Q, LL or WC involved | +0.0220 | +0.0072 | +0.0042 [+0.0003, +0.0079] | −0.0086 [−0.0129, −0.0043] | −0.0112 [−0.0156, −0.0068] |
| entry: no Q, LL or WC | +0.0169 | +0.0085 | +0.0000 [−0.0025, +0.0024] | −0.0039 [−0.0067, −0.0013] | −0.0043 [−0.0071, −0.0017] |
| overlapping: Q involved | +0.0155 | +0.0064 | +0.0036 [−0.0013, +0.0085] | −0.0100 [−0.0154, −0.0042] | −0.0143 [−0.0203, −0.0084] |
| thin history: <10 prior main-tour matches | +0.0296 | +0.0100 | +0.0081 [+0.0011, +0.0153] | −0.0139 [−0.0225, −0.0059] | −0.0151 [−0.0236, −0.0070] |
| thin history: 10-24 | +0.0183 | +0.0067 | −0.0006 [−0.0075, +0.0058] | −0.0111 [−0.0186, −0.0040] | −0.0128 [−0.0207, −0.0050] |
| thin history: >=100 | +0.0130 | +0.0059 | −0.0002 [−0.0035, +0.0030] | −0.0033 [−0.0067, +0.0001] | −0.0042 [−0.0076, −0.0009] |
| lower-ranked player's rank: 101-200 | +0.0152 | +0.0067 | +0.0015 [−0.0030, +0.0059] | −0.0084 [−0.0132, −0.0034] | −0.0115 [−0.0164, −0.0061] |
| lower-ranked player's rank: >200 | +0.0423 | +0.0132 | +0.0095 [+0.0009, +0.0175] | −0.0118 [−0.0213, −0.0023] | −0.0144 [−0.0240, −0.0050] |
| rest: either player >=60 days since last main-tour match | +0.0341 | +0.0111 | +0.0088 [+0.0029, +0.0147] | −0.0053 [−0.0124, +0.0016] | −0.0091 [−0.0162, −0.0021] |
| round: QF or later (incl. RR) | +0.0153 | +0.0077 | +0.0006 [−0.0046, +0.0057] | +0.0003 [−0.0050, +0.0054] | +0.0003 [−0.0050, +0.0056] |
| workload: either player >=9 main-tour matches in prior 28 days | +0.0161 | +0.0132 | +0.0059 [−0.0015, +0.0130] | +0.0024 [−0.0050, +0.0097] | +0.0017 [−0.0056, +0.0092] |
| level: Grand Slam | +0.0209 | +0.0115 | +0.0032 [−0.0017, +0.0080] | −0.0041 [−0.0096, +0.0009] | −0.0065 [−0.0120, −0.0014] |

| ATP 2024, 2,681 matches | Elo | P0 | P1 | full_tier | Alcaraz |
|---|---:|---:|---:|---:|---:|
| rung − UTS formula | +0.0006 [−0.0075, +0.0086] | −0.0105 [−0.0175, −0.0035] | −0.0163 [−0.0235, −0.0084] | −0.0244 [−0.0330, −0.0151] | −0.0253 [−0.0339, −0.0158] |
| rung − Ingram point model | −0.0202 [−0.0316, −0.0082] | −0.0313 [−0.0435, −0.0192] | −0.0372 [−0.0486, −0.0262] | −0.0452 [−0.0569, −0.0341] | −0.0461 [−0.0580, −0.0349] |
| rung − BuildOak | +0.0215 [+0.0136, +0.0294] | +0.0103 [+0.0041, +0.0166] | +0.0045 [−0.0011, +0.0101] | −0.0036 [−0.0097, +0.0024] | −0.0045 [−0.0108, +0.0017] |

### E. Information sets

**E. What each rival uses that Alcaraz does not, and vice versa** (from the product benchmark docs and BuildOak's fit receipt).

| Rival | Uses that Alcaraz does not | Alcaraz uses that the rival does not |
|---|---|---|
| BuildOak | Round, seeding, draw size, head-to-head, nationality and handedness match-ups, streaks, tournament-history and many rolling serve/return windows (443 columns, main-tour history from 1985), fitted with a recipe its author tuned on validation ROC AUC. | Qualifying, Challenger and Futures history (tier-inclusive Elo, experience counts, tier serve/return replay), opponent-adjusted dynamic serve/return states, and entry status (the pinned BuildOak ATP code drops every entry_ column), plus past-only proper-score calibration. |
| UTS | Head-to-head, set-level and indoor/outdoor Elo variants, winning percentages by round, level, opponent rank and handedness, and backhand traits, in a fixed hand-weighted formula over ATP history from 1968. | Lower-tier history, serve/return point statistics, workload and rest, entry status, and any weights or calibration learned from outcomes (the UTS weights are fixed). |
| Ingram | A generative point-level structure: serve and return point-win abilities by surface, turned into match probabilities through the scoring system (best-of-3 vs 5). | Rankings, workload and rest, lower-tier history, entry status, player traits, a learned non-linear combiner and past-only calibration (the adaptation fixed 'no extra calibrator'). |
| Five Elo/ranking baselines | Nothing Alcaraz lacks in kind: each is one rating (pooled, Kovalchik, FiveThirtyEight surface or weighted Elo) or the ranking alone, from main-tour history; WElo also weights by game share. | Everything beyond a single rating: serve/return, rankings plus Elo together, workload, lower-tier history, entry status and a learned combiner. |

