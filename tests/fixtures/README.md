# Fixture provenance

## Numerical solver regression

The numerical precision regression in `tests/test_dynamics_numerical_repair.py` is
constructed in code from explicit constants and NumPy `default_rng` / PCG64 seed `713`.
It creates one artificial match with two synthetic players, a future date, a fictional
tournament, nine seeded prior states, and two seeded service-point contests. The fixed
state-key and RNG-call order are visible in the test. The seed was selected by a bounded
software-case search for a case that fails the superseded absolute-objective line search
and passes the repaired solver plus an independent BFGS comparison. No source row,
archived player identifier, match value, prior state, or transformed source value is used
in the construction.

The former `solver_precision_2005-06-25.json` fixture was removed because it was an exact
copy of a real archived match-level regression fixture. Its deletion from the current
tree does not remove it from prior Git objects. The repository's MIT license applies to
the new synthetic construction; it does not change the terms governing historical
source-derived data. The owner approved preserving this one historical file on
2026-09-14; [DATA_LICENSES.md](../../DATA_LICENSES.md) records its exact identity,
provenance, terms, and the exception's narrow scope.
