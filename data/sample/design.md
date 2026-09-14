# Synthetic sample design

This document is the bound design, bio contract and panel manifest companion for
the committed sample. The sample is fully synthetic: every player, event, result,
serve count, ranking and price was drawn from a seeded generator
(`tools/make_sample.py`, seed 20260913). No real player, match, result or market
price appears in it, and nothing in it is evidence about tennis.

The chain it exercises starts after the market join: rule carry-forward, the saved
SR02 replay, SR03 calibration, ranking qualification, the edition index, features,
the trait sidecar, the predictor and reporting configs, the model pipeline, the
barrier and the report. The published contrast is `full_minus_base` with the HGB
learner. Seasons 2011-2020; 60 players;
5350 panel rows.
