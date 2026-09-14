# G1 / rules-only / dev

EU snapshot + ONSSA cache + crop map + rules engine; exact-name lookups only; no model, no web

Run 2026-09-14T20:04:32, code 2516f7f-dirty, 83 cases, 0.1 s, cost $0.0000.

| Metric | Value |
|---|---|
| pass | 82/83 (99%) |
| verdict_accuracy | 82/83 (99%) |
| mrl_accuracy | 75/76 (99%) |
| substance_resolved | 75/76 (99%) |
| crop_resolved | 76/76 (100%) |
| abstain_on_unknown | 7/7 (100%) |
| red_recall | 43/44 (98%) |
| false_green | 0 |
| over_abstain | 1 |

| Stratum | Pass |
|---|---|
| changed | 28/28 (100%) |
| loq_stable | 16/17 (94%) |
| no_mrl_required | 3/3 (100%) |
| numeric_stable | 21/21 (100%) |
| unknown | 7/7 (100%) |
| upcoming | 7/7 (100%) |

## Failures (1)

- `g1-dev-046` [loq_stable] 'Halauxifène-méthyl' on 'Fraises' (2026-09-13): expected RED 0.02* (Halauxifen-methyl), got CANNOT_VERIFY None (None); failed: verdict_ok, substance_ok, mrl_ok, missed_red, over_abstain
