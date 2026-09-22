# Manual update, fixtures and settlement

The manual workflow now connects the accepted model bundle to a qualified private
history snapshot. All six configurations were exercised on two generated fixtures:
ATP/WTA Elo and five trained routes, seven forecasts in total. Independent reconstruction
matched the numerical features and probabilities; settlement controls also passed.
[The dated validation and freshness limits](D2_READINESS.md) define this acceptance.
The [September 16 retained-input replay](RETAINED_INPUT_REPLAY.md) separately validates serving-count fills and a partial current ATP tier increment.
No real forecast was issued by this rehearsal. The public example configuration still
reports unavailable inputs until the separate model bundle and private histories are bound.

**September 21, 2026 pilot.** The research archive's decisions D121 and D124 record the
first real batch issued through this workflow: Elo and ATP full-tier forecasts for two
Hangzhou qualifying matches, entered in the hash-chained ledger before the official
scheduled start. Actual start times and external timestamp proofs remain unverified, so
no forecast has a confirmed score and the pilot is not prospective performance evidence.

## Commands

These commands require a prepared workspace and the input schemas in [DESIGN.md](DESIGN.md).
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

The [D2 readiness check](D2_READINESS.md) is read-only and reports history, snapshot,
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

## Review history

| Attempt | Disposition and reason |
|---|---|
| Original `50518be` | Rejected: history eligibility, timezone, source/fixture binding, field qualification, write confinement and clean-clone defects. Original [design](DESIGN.md) and [freeze](FREEZE.json) retained. |
| First repair `542d85e` | Rejected: mutable version-manifest anchor and escaping leaf/temporary symlinks. [Repair contract](REPAIR.md). |
| Second repair `4295df4` | Rejected: settlement trusted a rewritten current pointer ahead of the earlier qualification. [Repair2 contract](REPAIR2.md). |
| Third repair `5089b24` | Scoped independent acceptance: 36/36 adversarial and positive controls, plus 62 affected tests. [Repair3 contract](REPAIR3.md). |

The separate research archive retains `LANE_D_REPAIR3_RECONSTRUCTION.md`, SHA-256
`8afad3ada6a8d6b014a961a100f20321e02854baaf0ab089d220551044a37e6c`.
Review reused the earlier `4295df4` full-suite result (471 passed, one optional skip) only
for unchanged code. That earlier result is not final merged-release CI. Product decisions
RB18–RB22 record the scope and acceptance; [data status](../DATA.md) records real-source
qualification and model-use limits.
