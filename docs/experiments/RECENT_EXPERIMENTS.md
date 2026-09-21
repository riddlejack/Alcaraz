# Recent experiments: compact public record

This page preserves completed, aggregate-only historical findings that inform
the landing page. All are exposed retrospective development comparisons; none
changes the released default or establishes prospective performance.

## Serve components

On **7,610 ATP 2021–2023 targets**, a first-in / first-win / second-win
component representation was compared with the accepted aggregate-service
predictor. The declared scalar primary contrast reduced log loss by
**0.000076780** and added four correct picks (+0.052562 percentage points),
but its paired 95% log-loss interval **[-0.001064195, +0.000905735]** and
accuracy interval both include zero. No component representation was promoted.

## Richer state geometry

On the same **7,610 ATP 2021–2023 targets**, state geometry versus support
features changed log loss by **+0.000146803** and accuracy by
**+0.144547 percentage points**. Both intervals include zero. The richer state
arm was not promoted.

## WTA selection

On **7,140 WTA matches across 167 editions (2021–2023)**, downstream
match-loss selection (P2) was compared with the matched inherited selection
(P0). Equal-year log-loss delta was **-0.000082**, with 95% interval
**[-0.001984, +0.001953]**. P2 made one more correct pick; its accuracy and
Brier intervals also include zero. The policy was deferred.

## Small-event Bundle A successor

On **292 matches from three events**, a bundled fitted-procedure refresh
improved log loss by **-0.00186769** and Brier by **-0.00169977**, but accuracy
declined by **-0.342466 percentage points**. Offsets, HGB weights, and
calibration changed together, so the result cannot identify a richer-state
component as its cause. With only three event clusters, it is an accepted
conditional narrow finding and its generalization remains inconclusive. It did
not change the default.

## Reading these results

The populations, feature definitions, weights, information assumptions, and
uncertainty plans differ across experiments. They should not be joined into a
single trajectory or used to claim an upper bound on future model families.
The detailed private research archive retains designs, attempt records, and
independent reviews; this product page intentionally contains only public-safe
aggregate interpretation.
