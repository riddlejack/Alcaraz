# Fixture provenance

## Numerical solver regression

The numerical precision regression in `tests/test_dynamics_numerical_repair.py` is a
bounded deterministic fixture bank constructed from explicit constants and NumPy
`default_rng` / PCG64 seeds 1 through 2,000. Each seed creates 12 artificial matches with
24 synthetic players, a future date, a fictional tournament, 75 generated prior states,
and 24 seeded service-point contests. The fixed construction and RNG-call order are
visible in the test. No source row, archived player identifier, match value, prior state,
or transformed source value is used.

The executing platform admits the first case for which the superseded absolute-objective
line search demonstrably fails its unchanged convergence gates and an independent BFGS
fit succeeds. The admitted case must then pass the current public `apply_batch` path and
the original objective (`<1e-9`) and parameter (`<=2e-7`) comparison tolerances. BFGS is
run in prior-standard-deviation coordinates to condition the independent optimization;
the objective, `gtol=1e-8`, `maxiter=1000`, and comparison gates are unchanged. This
platform-explicit bank replaces the earlier single seed 713, whose planted legacy
failure reproduced on macOS but not on the pinned Linux CI environment.

The former `solver_precision_2005-06-25.json` fixture was removed because it was an exact
copy of a real archived match-level regression fixture. Its deletion from the current
tree does not remove it from prior Git objects. The repository's MIT license applies to
the new synthetic construction; it does not change the terms governing historical
source-derived data. The owner approved preserving this one historical file on
2026-09-14; [DATA_LICENSES.md](../../DATA_LICENSES.md) records its exact identity,
provenance, terms, and the exception's narrow scope.
