# Recent experiments: compact public record

This page preserves completed, aggregate-only historical findings that inform
the landing page. All are exposed retrospective development comparisons; none
changes the released default or establishes prospective performance.

## Uncertainty through the final predictor

On **7,610 ATP 2021–2023 targets**, a fixed two-arm experiment tested whether
accounting for uncertainty in estimated serve/return strength improved the
final predictor. The challenger replaced two main-tour/lower-tier dynamic
probability inputs with the previously reviewed UNC01 joint uncertainty
mapping. The other 46 features, observations, HGB menu, training windows,
past-only selection and calibration procedure stayed the same.

The challenger **worsened log loss by 0.000156526**, with a paired four-week
95% interval **[−0.000312053, +0.000637206]**. It made **eight more correct
picks** (+0.1051 percentage points), but the accuracy interval also included
zero. Brier score worsened slightly; every registered four-week and
tournament-edition interval included zero.

The separately specified, exposed **2,681-match ATP 2024** extension showed
the same tradeoff: log loss +0.000377980 and three more correct picks. Its
primary eight-week log-loss interval [−0.000226557, +0.000994385] and both
registered block-length sensitivities included zero. The incumbent and its
existing buildoak comparison reproduced exactly.

**Retain the incumbent.** The earlier standalone uncertainty result did not
establish a benefit when carried through this final learning and calibration
procedure. This does not establish equivalence or rule out other uncertainty
models. The experiment reused 14 incumbent fits and fitted 14 challenger
cells; independent reconstruction accepted the forecasts, selections and
registered uncertainty calculations. These intervals condition on saved fits
and forecasts, and the 2024 extension is not an untouched holdout.

## Learner capacity and training window

On **7,610 ATP 2021–2023 targets**, a four-arm experiment held the existing
48-input feature states fixed while changing the HGB head's capacity and its
supervised training window. The incumbent selected between 200-tree heads with
7 or 15 leaves; larger heads used 600 trees with 31 or 63 leaves. The window
comparison was the original five years versus expansion from 2013. Selection
and calibration used earlier annual forecasts in every arm.

The prespecified larger-head-plus-expansion arm **worsened log loss by
0.003328270**, with a paired four-week-block 95% interval
**[+0.001463021, +0.005245977]**, and made **35 fewer correct picks**. Its
accuracy change was −0.4599 percentage points, with interval
[−1.0160, +0.0401] percentage points; the accuracy interval includes zero.
Log loss worsened in all three years, and completed-only scoring did not
reverse the result.

Larger capacity alone also worsened probability scores. Expansion alone was
inconclusive: log-loss delta −0.000120651, interval crossing zero, and 23 fewer
correct picks. Expansion reduced some of the larger head's penalty without
making that arm better than the incumbent. No arm advanced. This is a negative
result for the specified HGB/window choices, conditional on saved feature
states—not a ceiling for other learners or future information.

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
