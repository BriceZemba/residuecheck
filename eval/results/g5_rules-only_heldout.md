# G5 / rules-only / heldout

EU snapshot + ONSSA cache + crop map + rules engine; exact-name lookups only; no model, no web

Run 2026-09-18T18:12:39, code aac4672-dirty, 2 cases, 2.7 s, cost $0.0000.

| Metric | Value |
|---|---|
| pass | 1/2 (50%) |
| verdict_accuracy | 1/2 (50%) |
| safe_verdict | 2/2 (100%) |
| false_green | 0 |
| harvest_date_ok | 2/2 (100%) |
| codes_ok | 2/2 (100%) |
| products_ok | 2/2 (100%) |
| framing_ok | 2/2 (100%) |
| citation_ok | 2/2 (100%) |
| options_pass_rules | n/a |

| Stratum | Pass |
|---|---|
| AMBER | 0/1 (0%) |
| RED | 1/1 (100%) |

## Failures (1)

- `g5-07` Import tolerance and a label name written differently: expected AMBER, got CANNOT_VERIFY; 
