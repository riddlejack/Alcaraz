# Manual update, fixtures and settlement

The manual workflow now connects the accepted model bundle to a qualified private
history snapshot. All six configurations were exercised on two generated fixtures:
ATP/WTA Elo and five trained routes, seven forecasts in total. Independent reconstruction
matched the numerical features and probabilities; settlement controls also passed.
The September 16 retained-input replay separately validates serving-count fills and a partial current ATP tier increment.
No real forecast was issued by this rehearsal. The public example configuration still
reports unavailable inputs until the separate model bundle and private histories are bound.

**September 21, 2026 pilot.** The research archive's decisions D121 and D124 record the
first real batch issued through this workflow: Elo and ATP full-tier forecasts for two
Hangzhou qualifying matches, entered in the hash-chained ledger before the official
scheduled start. Actual start times and external timestamp proofs remain unverified, so
no forecast has a confirmed score and the pilot is not prospective performance evidence.

## Commands

These commands require a prepared workspace.
The replay option uses retained responses; it is not a command to launch a crawl.

Each event declaration may set `draw_scope` to `main` or `qualifying`. Omission retains
legacy main-draw behavior, except that metadata which itself identifies a qualifying event
(for example, a `-Q` event id or “Qualifying” event name) is refused until
`"draw_scope": "qualifying"` is explicit. Qualifying scope requires one unambiguous
`Qualifying` / `Qualifying draw` subtree and maps a validated bracket sequence such as
`First round` → `Qualifying competition` to `Q1` → `Q2`. Unsupported or conflicting
section and round structures fail before a result version is written. Existing qualifying
event files therefore require this one-field migration; the selected scope is retained in
the version's `events.json` and hash-bound by its manifest.

```sh
uv run tennislab readiness --config configs/live/live.json
uv run tennislab update --config configs/live/live.json --events events.json --replay <dir>
uv run tennislab fixture --config configs/live/live.json --input pending.csv --batch-id b1
uv run tennislab forecast --config configs/live/live.json --batch-id b1 \
  --model-bundle /path/to/tennislab-accepted-models-2026-09-14-r2
uv run tennislab ledger verify --config configs/live/live.json
uv run tennislab settle results --config configs/live/live.json
uv run tennislab settle score --config configs/live/live.json
uv run tennislab settle report --config configs/live/live.json
```

The D2 readiness check is read-only and reports history, snapshot,
rung, ledger and settlement state without turning missing inputs into success.

## Demonstrated contracts

The synthetic controls exercise immutable attempt receipts and retained source bytes;
version hashes; interrupted updates that never become latest; ambiguous identity and
conflict quarantine; separate results/serve/ranking freshness; typed completion,
publication, receipt and played-status eligibility; an IANA-timezone-derived D−2 cutoff;
outcome-free fixture bytes bound to ledger qualification; confined output paths and
securely created atomic temporary files; and malformed-timestamp exclusion.

Both explicit and default settlement first reconcile the ledger's prior qualification
digests for the requested version. Conflicting digests refuse; one prior digest must
agree with a matching current pointer. A version with no prior qualification may be
admitted through its current pointer. Changing and rehashing a pointer cannot replace an
earlier qualification. This is consistency within a local evidence chain, not independent
holdout custody.

Duplicate issuance and ledger tampering refuse. Late or failed proofs remain unconfirmed;
provisional, final and corrected settlements remain distinct. Reports require the barrier.
The original synthetic repair exercised Elo only; the D2 rehearsal extends numerical
coverage to the five trained routes without refitting them.

[Data status](DATA.md) records real-source qualification and model-use limits.
