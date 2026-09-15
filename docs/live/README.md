# Manual update, fixtures and settlement

Repair `5089b24fe29e351d6f5f1c18fc970038b9c2c3cb` is independently accepted within
its synthetic rehearsal scope. It demonstrates manual update, fixture qualification,
Elo issuance, ledger verification and settlement. No real forecast has been issued;
trained-rung feature routes are implemented but still return explicit unavailable records
until their model bundle and hash-bound state inputs are supplied. The qualified
real-history, six-rung D2 snapshot is still pending.

## Commands

These commands require a prepared workspace and the input schemas in [DESIGN.md](DESIGN.md).
The replay option uses retained responses; it is not a command to launch a crawl.

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
Only Elo issues forecasts in this scope.

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
