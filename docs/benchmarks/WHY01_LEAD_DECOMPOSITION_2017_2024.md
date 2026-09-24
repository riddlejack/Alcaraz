# Where the lead over public models comes from (WHY01), ATP 2017–2024

> **Exploratory, post-hoc, descriptive.** This page decomposes the saved forecasts of Alcaraz
> and every public model it was benchmarked against. No forecasting model was fitted; segments
> and cut-points were chosen after the aggregate results were known; the data are development
> seasons the research process has already seen. Every number traces to
> [why01.json](why01.json), which holds the full tables (segment rows and aggregates only, no
> match rows). The analysis reruns in about half a minute from the scripts kept in the
> research archive (`references/WHY01/`).

This is the published 2017–2024 decomposition; only the title's season span and this note were
added. The 2017–2025 version, with the
same segment definitions and 2025 as exposed retrospective data, is
[WHY01_LEAD_DECOMPOSITION.md](WHY01_LEAD_DECOMPOSITION.md).

> **Exploratory, post-hoc, descriptive.** Saved forecasts on development data that the research
> process has already seen. No forecasting model was fitted. Segments and cut-points were chosen
> after the aggregate result was known. Intervals condition on the saved forecasts.

"Alcaraz" is `full_tier_entry` (ARMS01 attempt 002 Arm 1). Every difference is Alcaraz minus the
rival (or later rung minus earlier rung) in natural-log loss per match; negative favours Alcaraz.
Intervals are 95% match-level bootstrap percentiles (2,000 draws, seed 20260924); † marks n < 300.
All numbers come from [why01.json](why01.json); `why01_tables.py` renders the tables from it.

## Findings

**1. The lead is concentrated where a player's main-tour record is thin.** Against BuildOak
(−0.0070 [−0.0095, −0.0046] on 18,972 matches; calendar-week cluster interval [−0.0098, −0.0044]),
the three segments carrying the most gap beyond their size are:

- **a qualifier, lucky loser or wild card in the match**: n = 6,583 (34.7%), −0.0117 [−0.0165, −0.0070], 57.8% of the gap;
- **the lower-ranked player ranked 101–200**: n = 4,926 (26.0%), −0.0123 [−0.0175, −0.0072], 45.3% of the gap;
- **a player with fewer than 10 prior main-tour matches**: n = 2,355 (12.4%), −0.0164 [−0.0255, −0.0075], 29.0% of the gap.

They overlap heavily (995 matches are in all three) because they describe the same kind of match:
a qualifier ranked outside the top 100 with little tour-level history. Together they cover 43.8% of
matches and 67.5% [49.9, 89.7] of the gap (−0.0108 [−0.0150, −0.0069]). Alcaraz still leads in
the other 56.2% (−0.0041 [−0.0071, −0.0010]). BuildOak is level in quarter-finals and later
(+0.0009 [−0.0046, +0.0071]; n = 3,367), in heavy-workload matches (+0.0022 [−0.0054, +0.0096])
and on grass (−0.0011 [−0.0084, +0.0060]). Eight of 36 segment-versus-rest contrasts exclude zero
(two are mirror pairs), against about 1.8 expected by chance, so the concentration is more than
noise. Which segment "owns" it cannot be identified, because the segments overlap.

The pattern repeats for every public rival (Table A2). Against UTS and Ingram (2024, 2,681
matches), the fewer-than-10 segment (12.7% of matches) carries 36.0% and 35.3% of the gap
(−0.0719 and −0.1283). Against the four Elo baselines it carries 22.4% to 24.9% on 12.4% of
matches. The ranking-only baseline is the exception: its gap is flat across history bands
(−0.0415 below 10 matches, −0.0382 at 100 or more), because a ranking already reflects lower-tier
results. It loses most in Grand Slams (−0.0515) and clear-favourite matches (−0.0435).

**2. The lead is mostly discrimination, not calibration, except against Ingram.** Perfect in-sample
recalibration of each rival (a diagnostic counterfactual, not a forecast) bounds how much of its
gap is calibration (Table B2):

- **BuildOak** is overconfident (slope 0.890 [0.859, 0.924]). Recalibration removes 14.2% of the
  gap; −0.0060 [−0.0083, −0.0037] remains, and Alcaraz ranks matches better (AUC +0.0076 [+0.0047, +0.0106]).
- **UTS** is overconfident (slope 0.834). Recalibration removes 18.5% (19.2% against the published
  `full_tier` side); −0.0206 [−0.0279, −0.0122] remains (AUC +0.0260 [+0.0152, +0.0365]).
- **Ingram** is strongly overconfident (slope 0.619 [0.549, 0.695]; top-decile forecast 0.928,
  observed 0.814). Recalibration removes 47.5% (48.5% against `full_tier`), but −0.0242
  [−0.0312, −0.0168] remains (AUC +0.0295 [+0.0203, +0.0392]).
- The five Elo/ranking baselines are well scaled (slopes 0.962 to 0.998). Recalibration removes
  1.5% to 9.1% of their gaps, mostly through the intercept. Player A is the lower ID and is the
  older player in 93.4% of matches, so their negative intercepts (−0.067 to −0.145) mean the
  ratings over-rate the older player. That is consistent with ratings lagging rising players.
  Alcaraz's intercept is −0.023.

**3. What Alcaraz knows that the rivals do not: lower-tier history first, entry status second.**
On the saved ladder over the same rows (Tables D1–D2), the rung before lower-tier history (P1)
is level with BuildOak: +0.0008 [−0.0013, +0.0030]. In thin-history matches P1 is behind BuildOak
(+0.0085 [+0.0004, +0.0164] below 10 matches; +0.0093 [+0.0032, +0.0152] after a long main-tour
absence). Adding qualifying, Challenger and Futures history (full_tier − P1) gains −0.0068
overall. The gain is −0.0239 [−0.0321, −0.0158] with a sub-10-match player, −0.0210 when the
lower-ranked player is outside the top 200, and +0.0011 [−0.0024, +0.0044] in quarter-finals and
later; −0.0123 in the union of the three segments against −0.0025 elsewhere. This block turns a
tie with BuildOak into −0.0059 [−0.0085, −0.0035].

The entry-status block (−0.0011 [−0.0017, −0.0005]) concentrates in matches with a qualifier
(−0.0039 [−0.0061, −0.0018]), after a long absence (−0.0036) and at Grand Slams (−0.0021). It
does not concentrate in thin-history matches (−0.0010 [−0.0028, +0.0010]). It carries draw
information, not history. BuildOak's pinned ATP code drops entry columns and reads only main-tour
files from 1985 (Table E), so neither block has a counterpart in BuildOak. On 2024, even the plain
Elo rung beats Ingram (−0.0202 [−0.0316, −0.0082]) and ties UTS (+0.0006 [−0.0075, +0.0086]).
Ingram's deficit is largely its own overconfidence. The UTS deficit opens with the learned
combiner (P0 − UTS −0.0105 [−0.0175, −0.0035]) and widens with each block.

**4. When they disagree, Alcaraz wins slightly more often and loses less when wrong.** Alcaraz
and BuildOak pick different winners in 2,186 matches (11.5%). Alcaraz is right in 1,147 and
BuildOak in 1,039 (52.5% [50.2, 54.5]), at almost equal mean confidence (0.554 against 0.559).
These matches carry 33.7% [16.8, 52.6] of the gap. With a probability difference of 0.15 or more
(1,214 matches), Alcaraz is closer to the outcome only 52.5% [49.8, 55.2] of the time, yet these
matches carry 40.5% of the gap (−0.0445 [−0.0668, −0.0221]). BuildOak is the more confident side
(0.656 against 0.635) and pays for it when wrong. Large disagreements are over-represented in
thin-history (ratio 1.87), outside-top-200 (1.76) and long-absence (1.58) matches, and
under-represented in quarter-finals and later (0.83). Against UTS and Ingram, disagreements carry
more of the gap (74.5% and 68.1% for the large ones), and the rival is the more confident side
(0.681 and 0.729 against 0.625 and 0.619). Against the Elo baselines, Alcaraz is the more
confident side and is closer 66.8% to 69.2% of the time.

**5. The market is the mirror image.** Alcaraz trails Pinnacle by +0.0101 [+0.0078, +0.0123] on
18,882 priced matches. The market's edge is discrimination (AUC −0.0122 [−0.0148, −0.0094]);
recalibrating the market does not help. It concentrates after a long main-tour absence (+0.0204
[+0.0138, +0.0275]), in R128/R64 matches (+0.0145) and at Grand Slams (+0.0142). In thin-history
matches Alcaraz trails the market by an average amount (+0.0099, excess −0.2 points): lower-tier
history lets it catch the public models there, not the market.

**Information sets.** Table E gives one sentence per rival. The fairness audit's common-input
control, where Alcaraz leads even on identical inputs (−0.0229 [−0.0325, −0.0140]), is a
**WTA 2024** result on 2,404 matches. The documents read contain no ATP common-input control. The
audit also notes that BuildOak's recipe was selected on ROC AUC, which rewards ordering and
ignores calibration. That is consistent with its overconfidence here (slope 0.890).

## What this does and does not show

- **Exploratory and post hoc.** The data are repeatedly exposed development seasons. The segments,
  cut-points (60 days, 9 matches in 28 days, 10/25/50/100 prior matches, rank bands) and the
  top-three rule were fixed after the aggregate results and after the README's qualifier screen.
  Nothing here is confirmatory, and no new model or feature is proposed or tested.
- **Accounting, not causation.** "Carries the gap" is an additive decomposition of fixed forecasts.
  The segments overlap, so their shares cannot be summed. Ladder increments compare separately
  selected and calibrated fits, so they mix feature effects with selection noise.
- **Uncertainty is understated.** Intervals are match-level and condition on saved forecasts.
  Calendar-week cluster intervals for every BuildOak segment are in [why01.json](why01.json) and are of
  similar width. No multiplicity correction is applied across 36 segments and nine rivals.
- **Measurement limits.** Thin history counts primary main-tour panel appearances from 2005 to D−2.
  Rest and workload are main-tour only, so a long "absence" mixes injury returns with players
  coming up from lower tiers. Wimbledon and the US Open 2022 carry no entry codes (245 targets,
  counted as none). Finals (103 matches) and other † cells are unstable.
- **Scope of the 2024 rows.** UTS and Ingram cover one season. The README pairs them with
  `full_tier`, which reproduces here (−0.0244 and −0.0452); tables use `full_tier_entry`, and
  [why01.json](why01.json) holds both. BuildOak's 2024-only gap straddles zero, so its 2024 share-of-gap
  figures are unbounded and not reported.
- **In-sample recalibration is not a forecast.** It fits two parameters on the outcomes it scores.
  It bounds the calibration component from above and says nothing about what a past-only fix would recover.

## Files and inputs

`why01_load.py` aligns the inputs and runs the checks. `why01_analysis.py` does every computation
and writes [why01.json](why01.json) and `INPUTS.tsv`. `why01_tables.py` renders the Tables section.
`why01_check_report.py` checks that every number traces to [why01.json](why01.json). `INPUTS.tsv` lists
the sha256 of all 90 files read. Every named input was found, and the published log losses
reproduce exactly.

## Tables

### A. Segment decomposition

**A1. Alcaraz − BuildOak by segment (18,972 ATP matches, 2017–2024).** Gap share = the segment's summed difference over the total; excess = gap share minus match share (percentage points); segment − rest = mean difference in the segment minus the rest. Italic rows overlap the entry split. † n < 300.

| Segment | n | Share | Alcaraz | BuildOak | Diff [95%] | Gap share | Excess share, pts [95%] | Segment − rest [95%] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all matches | 18,972 | 100.0% | 0.5976 | 0.6046 | −0.0070 [−0.0095, −0.0046] | 100.0% | +0.0 [+0.0, +0.0] | — |
| entry: Q, LL or WC involved | 6,583 | 34.7% | 0.5997 | 0.6115 | −0.0117 [−0.0165, −0.0070] | 57.8% | +23.1 [+4.9, +44.6] | −0.0072 [−0.0127, −0.0014] |
| entry: no Q, LL or WC | 12,389 | 65.3% | 0.5964 | 0.6009 | −0.0045 [−0.0073, −0.0018] | 42.2% | −23.1 [−44.6, −4.9] | +0.0072 [+0.0014, +0.0127] |
| level: Grand Slam | 3,860 | 20.3% | 0.5154 | 0.5221 | −0.0067 [−0.0124, −0.0014] | 19.4% | −0.9 [−15.5, +14.7] | +0.0004 [−0.0062, +0.0066] |
| level: Masters | 4,071 | 21.5% | 0.6100 | 0.6193 | −0.0092 [−0.0144, −0.0040] | 28.2% | +6.7 [−7.6, +24.2] | −0.0028 [−0.0087, +0.0032] |
| level: other tour (250/500) | 10,938 | 57.7% | 0.6213 | 0.6278 | −0.0065 [−0.0098, −0.0030] | 53.1% | −4.6 [−24.8, +13.8] | +0.0013 [−0.0038, +0.0064] |
| level: Finals † | 103 | 0.5% | 0.6626 | 0.6533 | +0.0093 [−0.0271, +0.0456] | −0.7% | −1.3 [−4.4, +1.5] | +0.0164 [−0.0199, +0.0518] |
| round: R128/R64 | 5,500 | 29.0% | 0.5704 | 0.5791 | −0.0087 [−0.0134, −0.0042] | 35.9% | +6.9 [−9.8, +26.3] | −0.0023 [−0.0080, +0.0033] |
| round: R32/R16 | 10,105 | 53.3% | 0.6043 | 0.6131 | −0.0088 [−0.0122, −0.0053] | 66.5% | +13.2 [−5.5, +34.8] | −0.0037 [−0.0088, +0.0016] |
| round: QF or later (incl. RR) | 3,367 | 17.7% | 0.6215 | 0.6206 | +0.0009 [−0.0046, +0.0071] | −2.3% | −20.1 [−40.0, −7.2] | +0.0097 [+0.0035, +0.0164] |
| surface: Hard | 11,039 | 58.2% | 0.5953 | 0.6027 | −0.0075 [−0.0106, −0.0041] | 61.8% | +3.6 [−16.0, +25.4] | −0.0010 [−0.0064, +0.0044] |
| surface: Clay | 5,721 | 30.2% | 0.6050 | 0.6135 | −0.0085 [−0.0135, −0.0034] | 36.4% | +6.2 [−12.9, +26.2] | −0.0021 [−0.0080, +0.0037] |
| surface: Grass | 2,212 | 11.7% | 0.5896 | 0.5907 | −0.0011 [−0.0084, +0.0060] | 1.9% | −9.8 [−23.5, +1.8] | +0.0067 [−0.0013, +0.0143] |
| lower-ranked player's rank: <=50 | 4,652 | 24.5% | 0.5964 | 0.6001 | −0.0037 [−0.0081, +0.0009] | 13.0% | −11.6 [−28.7, +2.3] | +0.0044 [−0.0008, +0.0098] |
| lower-ranked player's rank: 51-100 | 7,498 | 39.5% | 0.6073 | 0.6116 | −0.0043 [−0.0080, −0.0006] | 24.2% | −15.3 [−35.6, +2.2] | +0.0045 [−0.0007, +0.0095] |
| lower-ranked player's rank: 101-200 | 4,926 | 26.0% | 0.6055 | 0.6178 | −0.0123 [−0.0175, −0.0072] | 45.3% | +19.3 [+3.8, +40.8] | −0.0071 [−0.0132, −0.0014] |
| lower-ranked player's rank: >200 | 1,844 | 9.7% | 0.5464 | 0.5586 | −0.0122 [−0.0224, −0.0018] | 16.9% | +7.2 [−6.9, +21.1] | −0.0057 [−0.0164, +0.0051] |
| lower-ranked player's rank: unranked/missing † | 52 | 0.3% | 0.3460 | 0.3631 | −0.0172 [−0.0777, +0.0486] | 0.7% | +0.4 [−2.2, +2.9] | −0.0102 [−0.0705, +0.0555] |
| rank gap: <=20 | 5,184 | 27.3% | 0.6471 | 0.6510 | −0.0039 [−0.0084, +0.0008] | 15.2% | −12.1 [−30.7, +4.0] | +0.0043 [−0.0013, +0.0099] |
| rank gap: 21-50 | 6,058 | 31.9% | 0.6076 | 0.6153 | −0.0077 [−0.0119, −0.0033] | 34.8% | +2.9 [−14.8, +20.6] | −0.0009 [−0.0060, +0.0046] |
| rank gap: 51-100 | 4,420 | 23.3% | 0.5767 | 0.5848 | −0.0082 [−0.0137, −0.0027] | 27.1% | +3.8 [−11.9, +21.0] | −0.0015 [−0.0076, +0.0044] |
| rank gap: 101-200 | 2,172 | 11.4% | 0.5449 | 0.5546 | −0.0097 [−0.0177, −0.0021] | 15.8% | +4.3 [−7.8, +17.7] | −0.0030 [−0.0112, +0.0054] |
| rank gap: >200 | 1,086 | 5.7% | 0.5073 | 0.5152 | −0.0079 [−0.0213, +0.0057] | 6.4% | +0.7 [−11.0, +11.9] | −0.0009 [−0.0150, +0.0127] |
| rank gap: missing † | 52 | 0.3% | 0.3460 | 0.3631 | −0.0172 [−0.0777, +0.0486] | 0.7% | +0.4 [−2.2, +2.9] | −0.0102 [−0.0705, +0.0555] |
| Elo margin: close (lowest third of Elo margin) | 6,324 | 33.3% | 0.6648 | 0.6741 | −0.0093 [−0.0138, −0.0047] | 44.0% | +10.6 [−6.6, +30.8] | −0.0034 [−0.0090, +0.0021] |
| Elo margin: middle third | 6,324 | 33.3% | 0.6327 | 0.6392 | −0.0065 [−0.0108, −0.0021] | 30.8% | −2.5 [−21.7, +15.1] | +0.0008 [−0.0043, +0.0061] |
| Elo margin: clear favourite (top third) | 6,324 | 33.3% | 0.4951 | 0.5005 | −0.0053 [−0.0095, −0.0011] | 25.2% | −8.1 [−26.4, +10.2] | +0.0026 [−0.0030, +0.0078] |
| rest: either player >=60 days since last main-tour match | 2,906 | 15.3% | 0.5746 | 0.5825 | −0.0080 [−0.0153, −0.0010] | 17.4% | +2.0 [−13.0, +16.8] | −0.0011 [−0.0088, +0.0064] |
| rest: both <60 days | 16,066 | 84.7% | 0.6017 | 0.6086 | −0.0069 [−0.0095, −0.0042] | 82.6% | −2.0 [−16.8, +13.0] | +0.0011 [−0.0064, +0.0088] |
| workload: either player >=9 main-tour matches in prior 28 days | 1,633 | 8.6% | 0.5464 | 0.5442 | +0.0022 [−0.0054, +0.0096] | −2.7% | −11.3 [−23.2, −2.3] | +0.0101 [+0.0020, +0.0178] |
| workload: both <9 | 17,339 | 91.4% | 0.6024 | 0.6103 | −0.0079 [−0.0105, −0.0053] | 102.7% | +11.3 [+2.3, +23.2] | −0.0101 [−0.0178, −0.0020] |
| thin history: <10 prior main-tour matches | 2,355 | 12.4% | 0.5630 | 0.5794 | −0.0164 [−0.0255, −0.0075] | 29.0% | +16.6 [+2.3, +33.6] | −0.0107 [−0.0202, −0.0014] |
| thin history: 10-24 | 2,252 | 11.9% | 0.6106 | 0.6234 | −0.0128 [−0.0213, −0.0054] | 21.7% | +9.8 [−2.2, +24.3] | −0.0066 [−0.0155, +0.0015] |
| thin history: 25-49 | 2,989 | 15.8% | 0.6218 | 0.6291 | −0.0073 [−0.0134, −0.0006] | 16.3% | +0.5 [−14.0, +15.2] | −0.0003 [−0.0073, +0.0068] |
| thin history: 50-99 | 3,946 | 20.8% | 0.6073 | 0.6087 | −0.0014 [−0.0064, +0.0037] | 4.0% | −16.8 [−33.8, −3.1] | +0.0071 [+0.0013, +0.0130] |
| thin history: >=100 | 7,430 | 39.2% | 0.5896 | 0.5948 | −0.0052 [−0.0090, −0.0015] | 29.1% | −10.1 [−29.7, +8.3] | +0.0030 [−0.0022, +0.0081] |
| age: youngest player <=21 | 2,990 | 15.8% | 0.5954 | 0.6052 | −0.0099 [−0.0167, −0.0029] | 22.1% | +6.4 [−8.0, +22.5] | −0.0034 [−0.0108, +0.0039] |
| age: youngest >21 (or age missing) | 15,982 | 84.2% | 0.5980 | 0.6045 | −0.0065 [−0.0091, −0.0039] | 77.9% | −6.4 [−22.5, +8.0] | +0.0034 [−0.0039, +0.0108] |
| completion: retired or defaulted | 497 | 2.6% | 0.6884 | 0.6948 | −0.0064 [−0.0236, +0.0110] | 2.4% | −0.3 [−7.2, +6.7] | +0.0007 [−0.0164, +0.0181] |
| completion: completed | 18,475 | 97.4% | 0.5951 | 0.6022 | −0.0070 [−0.0096, −0.0045] | 97.6% | +0.3 [−6.7, +7.2] | −0.0007 [−0.0181, +0.0164] |
| *overlapping: Q involved* | 3,943 | 20.8% | 0.6012 | 0.6160 | −0.0148 [−0.0211, −0.0081] | 43.6% | +22.9 [+6.3, +43.0] | −0.0098 [−0.0169, −0.0026] |
| *overlapping: LL involved* | 902 | 4.8% | 0.5943 | 0.5970 | −0.0026 [−0.0153, +0.0101] | 1.8% | −3.0 [−12.7, +5.8] | +0.0046 [−0.0089, +0.0175] |
| *overlapping: WC involved* | 2,192 | 11.6% | 0.6013 | 0.6135 | −0.0122 [−0.0208, −0.0040] | 20.1% | +8.6 [−4.3, +23.8] | −0.0059 [−0.0149, +0.0026] |
| *overlapping: PR involved* | 400 | 2.1% | 0.6110 | 0.6140 | −0.0030 [−0.0220, +0.0148] | 0.9% | −1.2 [−7.1, +4.7] | +0.0041 [−0.0153, +0.0222] |
| *overlapping: exactly one side Q* | 3,745 | 19.7% | 0.5989 | 0.6132 | −0.0143 [−0.0206, −0.0079] | 40.3% | +20.5 [+4.5, +40.3] | −0.0091 [−0.0163, −0.0020] |

**A2. The three segments with the largest excess gap share, per rival** (partition segments with n ≥ 300; post hoc).

| Rival (matches) | Overall diff [95%] | Rank | Segment | n | Diff [95%] | Gap share | Excess, pts [95%] |
|---|---:|---:|---|---:|---:|---:|---:|
| BuildOak (18,972) | −0.0070 [−0.0095, −0.0046] | 1 | entry: Q, LL or WC involved | 6,583 | −0.0117 [−0.0165, −0.0070] | 57.8% | +23.1 [+4.9, +44.6] |
|  |  | 2 | lower-ranked player's rank: 101-200 | 4,926 | −0.0123 [−0.0175, −0.0072] | 45.3% | +19.3 [+3.8, +40.8] |
|  |  | 3 | thin history: <10 prior main-tour matches | 2,355 | −0.0164 [−0.0255, −0.0075] | 29.0% | +16.6 [+2.3, +33.6] |
| Pooled Elo K32 (18,972) | −0.0250 [−0.0279, −0.0221] | 1 | lower-ranked player's rank: >200 | 1,844 | −0.0594 [−0.0740, −0.0449] | 23.1% | +13.4 [+8.2, +18.3] |
|  |  | 2 | rest: either player >=60 days since last main-tour match | 2,906 | −0.0455 [−0.0551, −0.0357] | 27.8% | +12.5 [+7.4, +17.7] |
|  |  | 3 | thin history: <10 prior main-tour matches | 2,355 | −0.0502 [−0.0620, −0.0388] | 24.9% | +12.5 [+7.2, +17.4] |
| Ranking logistic (18,972) | −0.0360 [−0.0397, −0.0325] | 1 | level: Grand Slam | 3,860 | −0.0515 [−0.0596, −0.0434] | 29.1% | +8.7 [+4.5, +13.0] |
|  |  | 2 | Elo margin: clear favourite (top third) | 6,324 | −0.0435 [−0.0501, −0.0373] | 40.3% | +7.0 [+2.1, +11.6] |
|  |  | 3 | round: R128/R64 | 5,500 | −0.0445 [−0.0520, −0.0372] | 35.8% | +6.8 [+1.9, +11.4] |
| Kovalchik Elo (18,972) | −0.0292 [−0.0324, −0.0262] | 1 | rest: either player >=60 days since last main-tour match | 2,906 | −0.0497 [−0.0599, −0.0397] | 26.1% | +10.7 [+6.3, +15.5] |
|  |  | 2 | thin history: <10 prior main-tour matches | 2,355 | −0.0535 [−0.0652, −0.0420] | 22.7% | +10.3 [+5.7, +14.7] |
|  |  | 3 | round: R128/R64 | 5,500 | −0.0391 [−0.0452, −0.0328] | 38.8% | +9.8 [+4.6, +14.6] |
| FiveThirtyEight surface Elo (18,972) | −0.0255 [−0.0285, −0.0227] | 1 | thin history: <10 prior main-tour matches | 2,355 | −0.0508 [−0.0622, −0.0397] | 24.7% | +12.3 [+7.4, +17.2] |
|  |  | 2 | entry: Q, LL or WC involved | 6,583 | −0.0345 [−0.0406, −0.0285] | 46.9% | +12.2 [+6.5, +18.0] |
|  |  | 3 | rest: either player >=60 days since last main-tour match | 2,906 | −0.0456 [−0.0555, −0.0357] | 27.4% | +12.1 [+7.1, +17.2] |
| WElo (18,972) | −0.0286 [−0.0318, −0.0256] | 1 | rest: either player >=60 days since last main-tour match | 2,906 | −0.0488 [−0.0587, −0.0387] | 26.1% | +10.8 [+6.3, +15.6] |
|  |  | 2 | lower-ranked player's rank: >200 | 1,844 | −0.0589 [−0.0733, −0.0449] | 20.0% | +10.3 [+5.9, +14.6] |
|  |  | 3 | thin history: <10 prior main-tour matches | 2,355 | −0.0515 [−0.0627, −0.0407] | 22.4% | +10.0 [+5.4, +14.4] |
| UTS formula (2024) (2,681) | −0.0253 [−0.0339, −0.0158] | 1 | entry: Q, LL or WC involved | 968 | −0.0428 [−0.0625, −0.0241] | 61.0% | +24.9 [+6.6, +43.8] |
|  |  | 2 | thin history: <10 prior main-tour matches | 340 | −0.0719 [−0.1138, −0.0307] | 36.0% | +23.4 [+5.6, +41.6] |
|  |  | 3 | lower-ranked player's rank: 101-200 | 677 | −0.0336 [−0.0558, −0.0115] | 33.5% | +8.3 [−11.1, +26.1] |
| Ingram point model (2024) (2,681) | −0.0461 [−0.0580, −0.0349] | 1 | thin history: <10 prior main-tour matches | 340 | −0.1283 [−0.1839, −0.0763] | 35.3% | +22.6 [+11.1, +34.6] |
|  |  | 2 | entry: Q, LL or WC involved | 968 | −0.0724 [−0.0974, −0.0484] | 56.6% | +20.5 [+7.8, +33.3] |
|  |  | 3 | lower-ranked player's rank: 101-200 | 677 | −0.0649 [−0.0939, −0.0376] | 35.5% | +10.2 [−2.3, +23.0] |
| Pinnacle (market, reference) (18,882) | +0.0101 [+0.0078, +0.0123] | 1 | rest: either player >=60 days since last main-tour match | 2,861 | +0.0204 [+0.0138, +0.0275] | 30.6% | +15.4 [+6.7, +25.3] |
|  |  | 2 | round: R128/R64 | 5,479 | +0.0145 [+0.0102, +0.0188] | 41.7% | +12.6 [+2.7, +23.7] |
|  |  | 3 | level: Grand Slam | 3,854 | +0.0142 [+0.0088, +0.0196] | 28.6% | +8.2 [−0.5, +18.2] |

**A3. Union of BuildOak's top three and the rest** (week-cluster = calendar-week cluster bootstrap sensitivity).

| BuildOak top three | n | Share | Alcaraz | BuildOak | Diff [95%] | Week-cluster [95%] | Gap share [95%] |
|---|---:|---:|---:|---:|---:|---:|---:|
| union of the three | 8,314 | 43.8% | 0.5970 | 0.6078 | −0.0108 [−0.0150, −0.0069] | [−0.0153, −0.0063] | 67.5% [+49.9, +89.7] |
| none of the three | 10,658 | 56.2% | 0.5980 | 0.6020 | −0.0041 [−0.0071, −0.0010] | [−0.0075, −0.0008] | 32.5% [+10.3, +50.1] |

Overlap counts: entry: Q, LL or WC involved & lower_ranked_player_rank: 101-200: 3,309; entry: Q, LL or WC involved & thin_history: <10 prior main-tour matches: 2,032; lower-ranked player's rank: 101-200 & thin_history: <10 prior main-tour matches: 1,204; all three: 995.

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

**A5. Five Elo/ranking baselines, Alcaraz − baseline by segment** (18,972; intervals in results.json).

| Segment | n | Pooled K32 | Rank logistic | Kovalchik | FiveThirtyEight | WElo |
|---|---:|---:|---:|---:|---:|---:|
| all matches | 18,972 | −0.0250 | −0.0360 | −0.0292 | −0.0255 | −0.0286 |
| entry: Q, LL or WC involved | 6,583 | −0.0327 | −0.0358 | −0.0369 | −0.0345 | −0.0363 |
| entry: no Q, LL or WC | 12,389 | −0.0209 | −0.0361 | −0.0251 | −0.0207 | −0.0245 |
| thin history: <10 prior main-tour matches | 2,355 | −0.0502 | −0.0415 | −0.0535 | −0.0508 | −0.0515 |
| thin history: 10-24 | 2,252 | −0.0270 | −0.0330 | −0.0358 | −0.0317 | −0.0305 |
| thin history: 25-49 | 2,989 | −0.0281 | −0.0326 | −0.0280 | −0.0261 | −0.0318 |
| thin history: 50-99 | 3,946 | −0.0201 | −0.0328 | −0.0235 | −0.0190 | −0.0236 |
| thin history: >=100 | 7,430 | −0.0178 | −0.0382 | −0.0230 | −0.0188 | −0.0221 |
| lower-ranked player's rank: <=50 | 4,652 | −0.0146 | −0.0337 | −0.0200 | −0.0145 | −0.0179 |
| lower-ranked player's rank: 51-100 | 7,498 | −0.0218 | −0.0328 | −0.0252 | −0.0216 | −0.0254 |
| lower-ranked player's rank: 101-200 | 4,926 | −0.0248 | −0.0343 | −0.0340 | −0.0310 | −0.0304 |
| lower-ranked player's rank: >200 | 1,844 | −0.0594 | −0.0509 | −0.0523 | −0.0504 | −0.0589 |
| round: R128/R64 | 5,500 | −0.0311 | −0.0445 | −0.0391 | −0.0329 | −0.0382 |
| round: R32/R16 | 10,105 | −0.0260 | −0.0351 | −0.0299 | −0.0271 | −0.0289 |
| round: QF or later (incl. RR) | 3,367 | −0.0121 | −0.0248 | −0.0109 | −0.0084 | −0.0121 |
| rest: either player >=60 days since last main-tour match | 2,906 | −0.0455 | −0.0388 | −0.0497 | −0.0456 | −0.0488 |
| level: Grand Slam | 3,860 | −0.0335 | −0.0515 | −0.0427 | −0.0351 | −0.0400 |
| Elo margin: clear favourite (top third) | 6,324 | −0.0232 | −0.0435 | −0.0269 | −0.0234 | −0.0264 |

### B. Calibration and discrimination

**B1. Per-system scores.** Recal = in-sample logistic regression of the outcome on logit(p); slope below 1 = overconfident. Reliability and resolution use deciles of each system's own forecast.

| System | Cohort | Log loss | Recal slope [95%] | Intercept | LL after recal | AUC [95%] | Brier | Reliability | Resolution |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Alcaraz (full_tier_entry) | 18,972 | 0.5976 | 1.010 [0.974, 1.048] | −0.023 | 0.5975 | 0.7387 [0.7318, 0.7455] | 0.2063 | 0.00031 | 0.04341 |
| full_tier (previous version) | 18,972 | 0.5986 | 1.009 [0.973, 1.046] | −0.023 | 0.5986 | 0.7374 [0.7304, 0.7443] | 0.2068 | 0.00028 | 0.04262 |
| BuildOak | 18,972 | 0.6046 | 0.890 [0.859, 0.924] | −0.005 | 0.6036 | 0.7311 [0.7243, 0.7382] | 0.2093 | 0.00059 | 0.03998 |
| Pooled Elo K32 | 18,972 | 0.6226 | 0.998 [0.957, 1.041] | −0.145 | 0.6203 | 0.7104 [0.7032, 0.7176] | 0.2170 | 0.00111 | 0.03328 |
| Ranking logistic | 18,972 | 0.6336 | 0.978 [0.934, 1.022] | −0.067 | 0.6330 | 0.6914 [0.6838, 0.6987] | 0.2219 | 0.00068 | 0.02823 |
| Kovalchik Elo | 18,972 | 0.6268 | 0.962 [0.922, 1.003] | −0.101 | 0.6255 | 0.7040 [0.6966, 0.7111] | 0.2187 | 0.00073 | 0.03123 |
| FiveThirtyEight surface Elo | 18,972 | 0.6230 | 0.969 [0.930, 1.010] | −0.119 | 0.6214 | 0.7096 [0.7024, 0.7168] | 0.2171 | 0.00092 | 0.03308 |
| WElo | 18,972 | 0.6261 | 0.972 [0.932, 1.013] | −0.137 | 0.6240 | 0.7056 [0.6985, 0.7129] | 0.2185 | 0.00112 | 0.03167 |
| Elo rung | 18,972 | 0.6238 | 0.885 [0.850, 0.924] | −0.144 | 0.6201 | 0.7103 [0.7032, 0.7175] | 0.2174 | 0.00159 | 0.03331 |
| P0 rung | 18,972 | 0.6122 | 1.026 [0.987, 1.068] | −0.132 | 0.6104 | 0.7225 [0.7153, 0.7298] | 0.2127 | 0.00109 | 0.03715 |
| P1 rung | 18,972 | 0.6054 | 0.998 [0.962, 1.038] | −0.029 | 0.6053 | 0.7300 [0.7231, 0.7370] | 0.2095 | 0.00020 | 0.03992 |
| Alcaraz (full_tier_entry) | 18,882 priced | 0.5974 | 1.012 [0.976, 1.050] | −0.022 | 0.5973 | 0.7388 [0.7319, 0.7457] | 0.2063 | 0.00033 | 0.04342 |
| Pinnacle (market, reference) | 18,882 priced | 0.5873 | 1.028 [0.992, 1.065] | −0.037 | 0.5871 | 0.7510 [0.7443, 0.7578] | 0.2020 | 0.00031 | 0.04734 |
| Alcaraz (full_tier_entry) | 2,681 (2024) | 0.5956 | 1.007 [0.912, 1.113] | −0.013 | 0.5955 | 0.7390 [0.7206, 0.7578] | 0.2057 | 0.00091 | 0.04440 |
| full_tier (previous version) | 2,681 (2024) | 0.5965 | 1.012 [0.915, 1.118] | −0.014 | 0.5965 | 0.7379 [0.7196, 0.7566] | 0.2062 | 0.00089 | 0.04319 |
| BuildOak | 2,681 (2024) | 0.6000 | 0.947 [0.852, 1.047] | +0.020 | 0.5998 | 0.7342 [0.7154, 0.7530] | 0.2077 | 0.00107 | 0.04185 |
| UTS formula | 2,681 (2024) | 0.6209 | 0.834 [0.746, 0.926] | −0.132 | 0.6162 | 0.7131 [0.6933, 0.7323] | 0.2164 | 0.00344 | 0.03624 |
| Ingram point model | 2,681 (2024) | 0.6417 | 0.619 [0.549, 0.695] | −0.131 | 0.6198 | 0.7096 [0.6904, 0.7287] | 0.2222 | 0.00679 | 0.03365 |

**B2. Share of each gap an in-sample recalibration of the rival would remove** (upper bound on the calibration component; diagnostic counterfactual, not a forecast).

| Alcaraz minus … | Cohort | Raw gap [95%] | vs rival recalibrated in-sample [95%] | Share of gap removed | Both recalibrated [95%] | AUC, Alcaraz − rival [95%] |
|---|---|---:|---:|---:|---:|---:|
| BuildOak | 18,972 | −0.0070 [−0.0095, −0.0046] | −0.0060 [−0.0083, −0.0037] | 14.2% | −0.0061 [−0.0084, −0.0039] | +0.0076 [+0.0047, +0.0106] |
| Pooled Elo K32 | 18,972 | −0.0250 [−0.0279, −0.0221] | −0.0227 [−0.0255, −0.0200] | 9.1% | −0.0228 [−0.0256, −0.0201] | +0.0283 [+0.0247, +0.0319] |
| Ranking logistic | 18,972 | −0.0360 [−0.0397, −0.0325] | −0.0355 [−0.0390, −0.0320] | 1.5% | −0.0355 [−0.0392, −0.0321] | +0.0473 [+0.0425, +0.0525] |
| Kovalchik Elo | 18,972 | −0.0292 [−0.0324, −0.0262] | −0.0279 [−0.0309, −0.0249] | 4.4% | −0.0280 [−0.0310, −0.0250] | +0.0347 [+0.0307, +0.0389] |
| FiveThirtyEight surface Elo | 18,972 | −0.0255 [−0.0285, −0.0227] | −0.0238 [−0.0266, −0.0210] | 6.6% | −0.0239 [−0.0267, −0.0211] | +0.0291 [+0.0255, +0.0328] |
| WElo | 18,972 | −0.0286 [−0.0318, −0.0256] | −0.0264 [−0.0294, −0.0235] | 7.6% | −0.0265 [−0.0295, −0.0235] | +0.0331 [+0.0291, +0.0371] |
| Pinnacle (market, reference) | 18,882 | +0.0101 [+0.0078, +0.0123] | +0.0103 [+0.0080, +0.0126] | −1.9% | +0.0103 [+0.0079, +0.0125] | −0.0122 [−0.0148, −0.0094] |
| BuildOak | 2,681 | −0.0045 [−0.0108, +0.0017] | −0.0042 [−0.0099, +0.0021] | 5.9% | −0.0042 [−0.0106, +0.0016] | +0.0049 [−0.0030, +0.0127] |
| UTS formula | 2,681 | −0.0253 [−0.0339, −0.0158] | −0.0206 [−0.0279, −0.0122] | 18.5% | −0.0206 [−0.0286, −0.0127] | +0.0260 [+0.0152, +0.0365] |
| Ingram point model | 2,681 | −0.0461 [−0.0580, −0.0349] | −0.0242 [−0.0312, −0.0168] | 47.5% | −0.0242 [−0.0317, −0.0173] | +0.0295 [+0.0203, +0.0392] |
| UTS formula | 2,681, full_tier side | −0.0244 [−0.0330, −0.0151] | −0.0197 [−0.0269, −0.0112] | 19.2% | −0.0197 [−0.0277, −0.0118] | +0.0248 [+0.0141, +0.0350] |
| Ingram point model | 2,681, full_tier side | −0.0452 [−0.0569, −0.0341] | −0.0233 [−0.0300, −0.0161] | 48.5% | −0.0233 [−0.0305, −0.0166] | +0.0283 [+0.0194, +0.0376] |

**B3. Reliability by forecast decile.**

| Decile | Alcaraz 18,972: mean p / observed | BuildOak 18,972: mean p / observed | Alcaraz 2024: mean p / observed | UTS 2024: mean p / observed | Ingram 2024: mean p / observed |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.166 / 0.154 | 0.140 / 0.168 | 0.152 / 0.119 | 0.160 / 0.160 | 0.106 / 0.164 |
| 2 | 0.279 / 0.271 | 0.254 / 0.276 | 0.278 / 0.254 | 0.285 / 0.261 | 0.243 / 0.299 |
| 3 | 0.343 / 0.344 | 0.330 / 0.363 | 0.344 / 0.381 | 0.366 / 0.354 | 0.337 / 0.366 |
| 4 | 0.404 / 0.429 | 0.398 / 0.422 | 0.400 / 0.463 | 0.432 / 0.493 | 0.421 / 0.474 |
| 5 | 0.465 / 0.467 | 0.463 / 0.462 | 0.457 / 0.455 | 0.500 / 0.489 | 0.502 / 0.433 |
| 6 | 0.526 / 0.494 | 0.528 / 0.502 | 0.514 / 0.474 | 0.562 / 0.515 | 0.576 / 0.506 |
| 7 | 0.591 / 0.559 | 0.594 / 0.560 | 0.577 / 0.567 | 0.621 / 0.595 | 0.654 / 0.575 |
| 8 | 0.661 / 0.650 | 0.668 / 0.639 | 0.649 / 0.627 | 0.693 / 0.562 | 0.738 / 0.644 |
| 9 | 0.745 / 0.756 | 0.754 / 0.747 | 0.744 / 0.750 | 0.775 / 0.679 | 0.827 / 0.687 |
| 10 | 0.867 / 0.874 | 0.878 / 0.858 | 0.871 / 0.870 | 0.880 / 0.851 | 0.928 / 0.814 |

Decile sizes: 1,897–1,898 (18,972) and about 268 (2,681).

### C. Disagreements

**C1. Different picks (forecasts on opposite sides of 0.5), then probability gaps of 0.15 or more.**

| Rival | Different picks (share) | Alcaraz right / rival right | Alcaraz right share [95%] | Mean confidence A / R | Diff [95%] | Share of total gap [95%] |
|---|---:|---:|---:|---:|---:|---:|
| BuildOak | 2,186 (11.5%) | 1,147 / 1,039 | 52.5% [50.2, 54.5] | 0.554 / 0.559 | −0.0206 [−0.0316, −0.0090] | 33.7% [+16.8, +52.6] |
| Pooled Elo K32 | 3,001 (15.8%) | 1,708 / 1,293 | 56.9% [55.2, 58.7] | 0.573 / 0.557 | −0.0463 [−0.0567, −0.0357] | 29.3% [+23.4, +34.9] |
| Ranking logistic | 3,793 (20.0%) | 2,221 / 1,572 | 58.6% [57.0, 60.1] | 0.588 / 0.568 | −0.0669 [−0.0782, −0.0560] | 37.2% [+32.1, +41.9] |
| Kovalchik Elo | 3,228 (17.0%) | 1,847 / 1,381 | 57.2% [55.5, 58.9] | 0.576 / 0.568 | −0.0605 [−0.0720, −0.0490] | 35.3% [+29.6, +40.7] |
| FiveThirtyEight surface Elo | 2,919 (15.4%) | 1,648 / 1,271 | 56.5% [54.7, 58.2] | 0.571 / 0.566 | −0.0545 [−0.0660, −0.0429] | 32.9% [+26.8, +38.5] |
| WElo | 3,301 (17.4%) | 1,882 / 1,419 | 57.0% [55.3, 58.7] | 0.578 / 0.567 | −0.0589 [−0.0704, −0.0475] | 35.9% [+30.2, +41.3] |
| UTS formula (2024) | 425 (15.9%) | 242 / 183 | 56.9% [52.1, 61.5] | 0.571 / 0.585 | −0.0891 [−0.1259, −0.0522] | 55.8% [+38.0, +77.3] |
| Ingram point model (2024) | 391 (14.6%) | 240 / 151 | 61.4% [56.8, 66.2] | 0.567 / 0.588 | −0.1000 [−0.1383, −0.0627] | 31.6% [+21.0, +43.5] |
| Pinnacle (market, reference) | 1,944 (10.3%) | 846 / 1,098 | 43.5% [41.3, 45.8] | 0.551 / 0.558 | +0.0329 [+0.0213, +0.0440] | 33.4% [+23.9, +43.6] |

| Rival | Probability gap ≥ 0.15 (share) | Alcaraz closer to outcome [95%] | Mean confidence A / R | Alcaraz LL / rival LL | Diff [95%] | Share of total gap [95%] |
|---|---:|---:|---:|---:|---:|---:|
| BuildOak | 1,214 (6.4%) | 637 = 52.5% [49.8, 55.2] | 0.635 / 0.656 | 0.6507 / 0.6951 | −0.0445 [−0.0668, −0.0221] | 40.5% [+23.7, +59.9] |
| Pooled Elo K32 | 2,292 (12.1%) | 1,586 = 69.2% [67.4, 71.1] | 0.699 / 0.610 | 0.5723 / 0.6819 | −0.1096 [−0.1271, −0.0932] | 53.0% [+47.2, +58.8] |
| Ranking logistic | 3,915 (20.6%) | 2,701 = 69.0% [67.6, 70.4] | 0.701 / 0.614 | 0.5697 / 0.6833 | −0.1136 [−0.1274, −0.1007] | 65.1% [+60.5, +69.9] |
| Kovalchik Elo | 2,739 (14.4%) | 1,831 = 66.8% [65.1, 68.6] | 0.678 / 0.631 | 0.5826 / 0.6994 | −0.1168 [−0.1335, −0.1009] | 57.7% [+52.2, +63.1] |
| FiveThirtyEight surface Elo | 2,299 (12.1%) | 1,538 = 66.9% [65.0, 68.9] | 0.674 / 0.633 | 0.5870 / 0.7041 | −0.1171 [−0.1352, −0.1005] | 55.7% [+49.7, +61.7] |
| WElo | 2,843 (15.0%) | 1,914 = 67.3% [65.7, 69.1] | 0.682 / 0.622 | 0.5794 / 0.6945 | −0.1151 [−0.1317, −0.0998] | 60.3% [+54.8, +66.0] |
| UTS formula (2024) | 370 (13.8%) | 215 = 58.1% [53.2, 63.0] | 0.625 / 0.681 | 0.6221 / 0.7588 | −0.1367 [−0.1854, −0.0871] | 74.5% [+57.1, +95.6] |
| Ingram point model (2024) | 459 (17.1%) | 248 = 54.0% [49.6, 58.5] | 0.619 / 0.729 | 0.6502 / 0.8338 | −0.1836 [−0.2366, −0.1313] | 68.1% [+56.3, +80.6] |
| Pinnacle (market, reference) | 814 (4.3%) | 316 = 38.8% [35.3, 42.2] | 0.625 / 0.656 | 0.6951 / 0.6223 | +0.0729 [+0.0448, +0.1017] | 31.0% [+21.3, +42.2] |

**C2. Over-representation among probability gaps ≥ 0.15** (share of the set over share of all matches).

| Segment | BuildOak: n in set, ratio | UTS 2024: n, ratio | Ingram 2024: n, ratio |
|---|---:|---:|---:|
| entry: Q, LL or WC involved | 606, 1.44 | 204, 1.53 † | 259, 1.56 † |
| thin history: <10 prior main-tour matches | 282, 1.87 † | 109, 2.32 † | 118, 2.03 † |
| thin history: 10-24 | 200, 1.39 † | 59, 1.39 † | 95, 1.81 † |
| lower-ranked player's rank: >200 | 208, 1.76 † | 78, 2.02 † | 66, 1.38 † |
| lower-ranked player's rank: 101-200 | 415, 1.32 | 134, 1.43 † | 163, 1.41 † |
| rest: either player >=60 days since last main-tour match | 294, 1.58 † | 77, 1.57 † | 84, 1.38 † |
| round: QF or later (incl. RR) | 179, 0.83 † | 41, 0.65 † | 70, 0.90 † |
| Elo margin: close (lowest third of Elo margin) | 507, 1.25 | 149, 1.21 † | 173, 1.13 † |

### D. Which block earns the lead where

**D1. Ladder increments by segment (later rung − earlier rung, 18,972 matches).**

| Segment | n | P0 − Elo [95%] | P1 − P0 [95%] | full_tier − P1 (lower tiers) [95%] | entry block [95%] |
|---|---:|---:|---:|---:|---:|
| all matches | 18,972 | −0.0116 [−0.0137, −0.0094] | −0.0068 [−0.0085, −0.0051] | −0.0068 [−0.0086, −0.0050] | −0.0011 [−0.0017, −0.0005] |
| union of BuildOak top three | 8,314 | −0.0161 [−0.0201, −0.0122] | −0.0038 [−0.0065, −0.0011] | −0.0123 [−0.0156, −0.0091] | −0.0022 [−0.0034, −0.0010] |
| none of BuildOak top three | 10,658 | −0.0081 [−0.0105, −0.0055] | −0.0091 [−0.0112, −0.0069] | −0.0025 [−0.0044, −0.0007] | −0.0002 [−0.0006, +0.0002] |
| entry: Q, LL or WC involved | 6,583 | −0.0169 [−0.0217, −0.0127] | −0.0021 [−0.0051, +0.0009] | −0.0134 [−0.0171, −0.0096] | −0.0025 [−0.0038, −0.0011] |
| entry: no Q, LL or WC | 12,389 | −0.0087 [−0.0110, −0.0063] | −0.0093 [−0.0113, −0.0072] | −0.0033 [−0.0051, −0.0015] | −0.0004 [−0.0008, +0.0001] |
| overlapping: Q involved | 3,943 | −0.0120 [−0.0177, −0.0066] | −0.0023 [−0.0059, +0.0013] | −0.0136 [−0.0184, −0.0086] | −0.0039 [−0.0061, −0.0018] |
| thin history: <10 prior main-tour matches | 2,355 | −0.0225 [−0.0317, −0.0138] | −0.0014 [−0.0066, +0.0036] | −0.0239 [−0.0321, −0.0158] | −0.0010 [−0.0028, +0.0010] |
| thin history: 10-24 | 2,252 | −0.0116 [−0.0183, −0.0051] | −0.0090 [−0.0144, −0.0038] | −0.0083 [−0.0143, −0.0022] | −0.0015 [−0.0035, +0.0004] |
| thin history: >=100 | 7,430 | −0.0073 [−0.0106, −0.0041] | −0.0062 [−0.0087, −0.0037] | −0.0033 [−0.0054, −0.0012] | −0.0008 [−0.0016, −0.0001] |
| lower-ranked player's rank: 101-200 | 4,926 | −0.0088 [−0.0133, −0.0041] | −0.0053 [−0.0088, −0.0019] | −0.0101 [−0.0143, −0.0059] | −0.0026 [−0.0039, −0.0012] |
| lower-ranked player's rank: >200 | 1,844 | −0.0333 [−0.0446, −0.0211] | −0.0015 [−0.0074, +0.0044] | −0.0210 [−0.0292, −0.0128] | −0.0023 [−0.0045, −0.0001] |
| rest: either player >=60 days since last main-tour match | 2,906 | −0.0244 [−0.0325, −0.0166] | −0.0024 [−0.0066, +0.0021] | −0.0137 [−0.0200, −0.0074] | −0.0036 [−0.0054, −0.0020] |
| round: QF or later (incl. RR) | 3,367 | −0.0088 [−0.0140, −0.0040] | −0.0077 [−0.0119, −0.0037] | +0.0011 [−0.0024, +0.0044] | −0.0000 [−0.0012, +0.0011] |
| workload: either player >=9 main-tour matches in prior 28 days | 1,633 | −0.0037 [−0.0092, +0.0026] | −0.0085 [−0.0133, −0.0034] | −0.0033 [−0.0073, +0.0005] | −0.0009 [−0.0023, +0.0005] |
| level: Grand Slam | 3,860 | −0.0105 [−0.0148, −0.0059] | −0.0097 [−0.0134, −0.0058] | −0.0061 [−0.0100, −0.0022] | −0.0021 [−0.0031, −0.0011] |

**D2. Each rung minus BuildOak (18,972), and each rung minus the 2024 rivals (2,681).**

| Segment | Elo − BO | P0 − BO | P1 − BO [95%] | full_tier − BO [95%] | Alcaraz − BO [95%] |
|---|---:|---:|---:|---:|---:|
| all matches | +0.0192 | +0.0076 | +0.0008 [−0.0013, +0.0030] | −0.0059 [−0.0085, −0.0035] | −0.0070 [−0.0095, −0.0046] |
| union of BuildOak top three | +0.0235 | +0.0074 | +0.0036 [−0.0000, +0.0070] | −0.0086 [−0.0126, −0.0047] | −0.0108 [−0.0150, −0.0069] |
| none of BuildOak top three | +0.0158 | +0.0078 | −0.0013 [−0.0042, +0.0016] | −0.0038 [−0.0068, −0.0007] | −0.0041 [−0.0071, −0.0010] |
| entry: Q, LL or WC involved | +0.0231 | +0.0062 | +0.0041 [−0.0000, +0.0082] | −0.0093 [−0.0138, −0.0046] | −0.0117 [−0.0165, −0.0070] |
| entry: no Q, LL or WC | +0.0171 | +0.0084 | −0.0009 [−0.0035, +0.0018] | −0.0042 [−0.0070, −0.0013] | −0.0045 [−0.0073, −0.0018] |
| overlapping: Q involved | +0.0171 | +0.0051 | +0.0028 [−0.0027, +0.0079] | −0.0108 [−0.0168, −0.0049] | −0.0148 [−0.0211, −0.0081] |
| thin history: <10 prior main-tour matches | +0.0324 | +0.0099 | +0.0085 [+0.0004, +0.0164] | −0.0154 [−0.0247, −0.0065] | −0.0164 [−0.0255, −0.0075] |
| thin history: 10-24 | +0.0176 | +0.0061 | −0.0030 [−0.0100, +0.0040] | −0.0113 [−0.0193, −0.0037] | −0.0128 [−0.0213, −0.0054] |
| thin history: >=100 | +0.0125 | +0.0051 | −0.0010 [−0.0046, +0.0026] | −0.0044 [−0.0082, −0.0008] | −0.0052 [−0.0090, −0.0015] |
| lower-ranked player's rank: 101-200 | +0.0145 | +0.0057 | +0.0005 [−0.0042, +0.0048] | −0.0096 [−0.0147, −0.0049] | −0.0123 [−0.0175, −0.0072] |
| lower-ranked player's rank: >200 | +0.0458 | +0.0125 | +0.0111 [+0.0024, +0.0197] | −0.0099 [−0.0203, +0.0004] | −0.0122 [−0.0224, −0.0018] |
| rest: either player >=60 days since last main-tour match | +0.0362 | +0.0117 | +0.0093 [+0.0032, +0.0152] | −0.0043 [−0.0115, +0.0026] | −0.0080 [−0.0153, −0.0010] |
| round: QF or later (incl. RR) | +0.0164 | +0.0075 | −0.0002 [−0.0056, +0.0055] | +0.0009 [−0.0046, +0.0068] | +0.0009 [−0.0046, +0.0071] |
| workload: either player >=9 main-tour matches in prior 28 days | +0.0186 | +0.0149 | +0.0064 [−0.0012, +0.0137] | +0.0031 [−0.0043, +0.0107] | +0.0022 [−0.0054, +0.0096] |
| level: Grand Slam | +0.0217 | +0.0112 | +0.0015 [−0.0038, +0.0069] | −0.0046 [−0.0103, +0.0010] | −0.0067 [−0.0124, −0.0014] |

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

