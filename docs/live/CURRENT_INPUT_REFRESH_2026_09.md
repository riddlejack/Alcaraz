# September 2026 private input refresh

A bounded September 22 refresh exercises the existing accepted models with
newer inputs. It advances data freshness without retraining or changing the
released predictor. The private source snapshot and generated inference were
independently reviewed; they are not a population-complete dataset or a
demonstrated improvement in forecasting accuracy.

| Input | Accepted change | Remaining limit |
|---|---|---|
| ATP rankings | 450 identity-resolved September 21 ranks; 99 of the top 100 | One top-100 identity remains ambiguous; current ranking points are missing |
| WTA rankings | 476 identity-resolved September 21 ranks; all top 100 | Current ranking points are missing |
| Main-history serve counts | 57 exact fills: three ATP and 54 WTA | Targeted player coverage; not a whole-tour refresh |
| WTA results | Two current-receipt additions | Current receipt does not establish historical availability |
| ATP lower-tier history | 91 additional post-June rows for six players | Declared date proxies; not full lower-tier coverage |

The preceding accepted snapshot supplied six player identities and seven
qualifying results. The successor preserves those additions. September ranks
are paired with missing points rather than stale June points. Older accepted
historical snapshots and benchmark inputs remain unchanged.

All three generated matchups qualified in both the baseline and successor
workspaces. All eleven requested forecasts ran in each workspace, spanning
Elo and the five trained routes; both local ledgers verified. Probability
changes demonstrate that updated inputs are consumed. The fixtures were
generated behavior checks, so these changes are not accuracy measurements,
real scheduled forecasts or prospective validation.

The supporting product fixes prevent a live result already included in bound
history from being counted twice by Elo and preserve an unchanged tour's
history coverage when an incremental update contains the other tour only.

## Private snapshot identity

- Version: `20260922T170209Z-54e35fbe`.
- Content SHA-256: `54e35fbecf76b26740a9549460ffac76a9e0fa0a879a272161faf0de35668211`.
- Config SHA-256: `58e5466f91c7bfa5083f4236482788c0d2aed94dbeae1401aeffd590129b94a0`.
- Input-manifest SHA-256: `9594b91a6f888b0d716c52ad898217ddbfd7fc8f85f546967f778012b106e33a`.

Raw pages, ranking rows, player histories and generated fixture outputs remain
in the private research archive. The public configuration still requires
separately qualified input bindings and the accepted model bundle. See the
[manual workflow](README.md) for its interface and
[data licences](../../DATA_LICENSES.md) for the source boundary.

Source: Jeff Sackmann / Tennis Abstract, acquired September 22, 2026 under the
project's recorded collection permission; source-derived data remain subject
to CC BY-NC-SA 4.0. The earlier qualifying-result additions retain their
Wikipedia source/revision attribution under CC BY-SA 4.0. This page publishes
aggregate coverage and artifact identities, not source rows.
