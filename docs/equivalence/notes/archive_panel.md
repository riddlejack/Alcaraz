# archive_panel
Base revision: WTA02_models/build_archive_panel.py + run_archive_panel.py (superset of TIER01: tour profile, optional bridge, player-master extraction). ATP behaviour unchanged.
ATP TIER01/attempt_002: identical 7/9 (source_panel.csv, annual_stats.csv, anomalies.csv, correction_log.csv, input_manifest.json, stdout.txt, stderr.txt); differing: archive_panel_launch.json (provenance only: code receipt, launcher id, `tour`, `rebound_constants` dropped), quality_report.json (three descriptive keys added by the WTA02 revision: `tour`, `correction_policy`, `excluded_reason_counts`; every shared key identical).
WTA WTA02/attempt_002: pending (bridge in WTA mode not yet ported).
Label reads: none (the panel carries `a_won` as a source column; nothing is scored).
Learned constants: none.
Open: nothing.
