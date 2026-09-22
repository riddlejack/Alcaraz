# Saved-forecast fairness audit

`reconstruct.py` re-joins an accepted ATP2024 or WTA2024 BuildOak comparison from its forecast commitment, frozen panel/labels and incumbent forecast carrier. It verifies bound inputs and all committed model/forecast outputs, enforces exact full target membership and canonical orientation, compares the rebuilt paired rows with the accepted rows, checks annual source winner identities, and recomputes log loss, Brier, accuracy and paired stationary-week uncertainty. It fits no model and changes no saved forecast.

Private archive files are required and remain outside Git. From this checkout's locked environment:

```sh
uv run python tools/buildoak_audit/reconstruct.py \
  --authorization "$AUDIT_AUTHORIZATION" \
  --attempt "$AUDIT_ACCEPTED_ATTEMPT" \
  --tour ATP \
  --output "$AUDIT_NEW_OUTPUT"
```

Use WTA for that tour's separately bound input set. The output path must not exist. Seeds, 5,000 replicates and block lengths8/4/13 preserve the accepted uncertainty designs; ATP's Brier and accuracy intervals are supplemental audit diagnostics. All intervals condition on fixed forecasts. Source identity agreement is not independent verification of every historical result or timestamp.

`shared_data.py` implements the separately frozen WTA shared-data diagnostic. It
requires the private accepted WTA01 inputs and the exact retained isolated Docker
image. `prepare` constructs the qualified carriers and records exclusions;
`equivalence` checks whether the incumbent's consumed inputs are unchanged;
`project` generates features without fitting; and `forecast` requires a separate
owner-frozen authorization before fitting the existing native recipe. The tool is
specific to the accepted 10,496 training keys and 2,404 targets. It is not a general
training service or a clean-clone source-data download command.

```sh
uv run python tools/buildoak_audit/shared_data.py --help
uv run python tools/buildoak_audit/shared_data.py project \
  --authorization "$AUDIT_FEATURE_AUTHORIZATION"
uv run python tools/buildoak_audit/shared_data.py forecast \
  --authorization "$AUDIT_FIT_AUTHORIZATION"
uv run python -m tools.buildoak_audit.score_shared \
  --attempt "$AUDIT_SHARED_ATTEMPT" \
  --baseline "$AUDIT_RECONSTRUCTED_WTA_ROWS" \
  --panel "$AUDIT_WTA_PANEL" \
  --output "$AUDIT_NEW_SCORE_OUTPUT"
```

The scorer verifies the forecast commitment and separately bound baseline, panel,
scorer and imported metric module. Its three contrasts keep the original
full-system comparison primary, report the shared-data control separately, and
measure the external model's combined input-policy intervention. No new
calibration, candidate selection or model fit occurs during scoring.
