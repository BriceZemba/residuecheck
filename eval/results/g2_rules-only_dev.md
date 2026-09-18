# G2 / rules-only / dev

EU snapshot + ONSSA cache + crop map + rules engine; exact-name lookups only; no model, no web

Run 2026-09-18T18:14:23, code aac4672-dirty, 42 cases, 0.8 s, cost $0.0000.

| Metric | Value |
|---|---|
| pass | 35/42 (83%) |
| product_identified | 28/35 (80%) |
| wrong_product | 0 |
| abstained_on_real | 7 |
| substances_exact | 28/28 (100%) |
| registration_accuracy | 28/28 (100%) |
| dar_accuracy | 28/28 (100%) |
| fake_accepted | 0 |
| right_first_suggestion | 7/7 (100%) |

| Stratum | Pass |
|---|---|
| exact | 28/28 (100%) |
| fake | 7/7 (100%) |
| variant | 0/7 (0%) |

## Failures (7)

- `g2-dev-029` [variant] 'BARKLAY BARBARIAN SUPER 360' on 'Mandarins': expected found BARCLAY BARBARIAN SUPER 360 registered=True DAR=None, got not_found  registered=None DAR=None; failed: product_ok, abstained
- `g2-dev-030` [variant] 'CR0NOS' on '(a) potatoes': expected found CRONOS registered=True DAR=30, got not_found  registered=None DAR=None; failed: product_ok, abstained
- `g2-dev-031` [variant] 'KATANGA TR1PLE' on 'Table grapes': expected found KATANGA TRIPLE registered=True DAR=28, got not_found  registered=None DAR=None; failed: product_ok, abstained
- `g2-dev-032` [variant] 'KUIVREVAL 20 WG' on '(a) potatoes': expected found CUIVREVAL 20 WG registered=True DAR=15, got not_found  registered=None DAR=None; failed: product_ok, abstained
- `g2-dev-033` [variant] 'SOUPYTO' on 'Table grapes': expected found SOUPHYTO registered=True DAR=None, got not_found  registered=None DAR=None; failed: product_ok, abstained
- `g2-dev-034` [variant] 'VELUM PR1ME' on 'Melons': expected found VELUM PRIME registered=True DAR=3, got not_found  registered=None DAR=None; failed: product_ok, abstained
- `g2-dev-035` [variant] 'ZOXYBIN' on 'Tomatoes': expected found ZOXYBIN 25 SC registered=True DAR=3, got not_found  registered=None DAR=None; failed: product_ok, abstained
