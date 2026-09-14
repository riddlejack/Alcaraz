# preflight
Base revision: TIER01_models/runner.py `preflight` (WTA02 additions merged under the tour switch: `configure_identity`, `configure_cohort`, and the two dynamic-feature dispersion blocks in the output). Module: `tennislab.models.pipeline`.
ATP TIER01/attempt_002: identical 1/2 (stderr.txt); differing: stdout.txt — `config_path` (archive absolute path -> workspace-relative), the archive's `numerical_sha256`/`runner_sha256` leaves replaced by `declared_binding` (the config's `code` block, recorded) and `code` (package receipts for `tennislab.models.pipeline` and `tennislab.models.numerical`). `status`, `config_sha256`, `input_hashes`, `membership` (26,149 raw primary; 18,972 selected; 2,376 warm-up; 110 attempts) and `ordered_model_columns_sha256` are identical.
WTA WTA02/attempt_002: identical 1/2; the same stdout leaves; `membership` (11,477 raw primary; 4,296 selected; 100 attempts) and both dispersion blocks identical.
Label reads: none (the bundle is assembled and counted from feature/sidecar metadata; the label file is hashed against its binding only).
Learned constants: none.
Open: nothing.
