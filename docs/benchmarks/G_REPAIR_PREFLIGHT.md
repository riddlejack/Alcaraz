# Lane G repair preflight

Date: 2026-09-14  
Rejected implementation: `bf73d1eec95e9586602ea7e2ed33c34228720f3c`  
Frozen repair-contract commit: `1535ded22a45381d5a2fa2431245ab1af61fab15`

Command:

```text
uv run pytest -q tests/test_benchmark_repair_regressions.py
```

Result before executable repair: **8 failed, 0 passed**.

The public plants reproduced the reviewed defects:

- G1 returned the old pooled-fit object rather than the equal-year slope-zero result;
- G2 serialized `0.00000001` as a clipped value near `1e-6`;
- G3 parsed a final unavailable outcome and failed;
- G4 accepted both a mutated prediction and an emptied forecast stage;
- G5 accepted a sensitive uppercase `.CSV.GZ` plant;
- G6 accepted fixed-constant drift;
- G7 lacked the complete paired-score/market/sensitivity report structure.

This is negative-control evidence only. Passing the same controls after repair establishes
bounded conformance, not model quality or independent acceptance.
