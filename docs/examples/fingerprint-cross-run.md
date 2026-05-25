# Example: cross-run fingerprinting

After two consecutive `bin/arip-e2e.sh` runs against a clean stack,
the SQLite memory store (`.arip/memory.db`) looks like this:

```
## investigations
id  test                                      rule                     fingerprint     
--  ----------------------------------------  -----------------------  ----------------
1   checkout returns 200 OK (FAILS under inv  downstream_error         2db23e4e389cfa6b
2   checkout latency stays within SLA under   db_pool_exhaustion       cacda21ed02e005b
3   checkout succeeds without exhausting ret  retry_storm              193713f185d4ac66
4   order transitions stay non-interleaved a  concurrent_modification  29cb8520c4f61051
5   checkout returns 200 OK (FAILS under inv  downstream_error         2db23e4e389cfa6b
6   checkout latency stays within SLA under   db_pool_exhaustion       cacda21ed02e005b
7   checkout succeeds without exhausting ret  retry_storm              193713f185d4ac66
8   order transitions stay non-interleaved a  concurrent_modification  29cb8520c4f61051

## test_runs (per-test pass/fail history)
test                                                          status  n
------------------------------------------------------------  ------  -
checkout latency stays within SLA under concurrent load (FAI  failed  2
checkout returns 200 OK (FAILS under inventory_error)         failed  2
checkout succeeds with confirmed status (baseline)            passed  2
checkout succeeds without exhausting retries (FAILS under re  failed  2
order transitions stay non-interleaved across traces          failed  2
```

**What this tells you.**

Eight investigations across two runs, four distinct fingerprints.
Each rule + service + evidence-shape combination collapses to a
stable 16-char hash; that hash is what makes "this same root-cause
shape has been seen N time(s)" possible without ever comparing trace
IDs, order IDs, or timestamps.

The `test_runs` table is the feed for the flaky-test classifier.
After enough runs (≥ 5), it returns `flaky | genuine | unknown` for
each test name; reports show that verdict inline.

**Fingerprint formula:**

```
fingerprint = sha256(
    rule_id
    + sorted(distinct service names from evidence)
    + sorted multiset of evidence kinds, e.g. {span:5, log:6}
)[:16]
```

Trace IDs, span IDs, order IDs, and timestamps are **explicitly not**
included — they vary per run; the fingerprint should not.
