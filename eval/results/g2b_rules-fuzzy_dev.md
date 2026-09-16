# G2B / rules-fuzzy / dev

rules-only plus fuzzy ONSSA name suggestions with a clear margin; no model, no web

Run 2026-09-16T21:30:06, code 7c2bf8c-dirty, 10 cases, 0.1 s, cost $0.0000.

| Metric | Value |
|---|---|
| pass | 2/10 (20%) |
| product_identified | 0/8 (0%) |
| substances_exact | n/a |
| wrong_product | 0 |
| abstained_on_real | 8 |
| fake_accepted | 0 |

| Stratum | Pass |
|---|---|
| eg_exact | 0/4 (0%) |
| fake | 2/2 (100%) |
| tr_exact | 0/4 (0%) |

## Failures (8)

- `g2b-dev-001` [tr_exact] 'AZOSTAR 320 SC' (TR): expected found AZOSTAR 320 SC ['Tebuconazole', 'Azoxystrobin'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-002` [tr_exact] 'BEST FORTE 80 WG' (TR): expected found BEST FORTE 80 WG ['Thiram'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-003` [tr_exact] 'METIKOLOS' (TR): expected found METIKOLOS ['Fluazinam', 'Cymoxanil'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-004` [tr_exact] 'ROYTAİ 150 ZEC' (TR): expected found ROYTAİ 150 ZEC ['Chlorantraniliprole', 'lambda-Cyhalothrin'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-005` [eg_exact] 'اييزو 30% WG' (EG): expected found اييزو 30% WG ['Indoxacarb'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-006` [eg_exact] 'كانزابريس 30% SC' (EG): expected found كانزابريس 30% SC ['Picoxystrobin'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-007` [eg_exact] 'ليكوبار 40% SE' (EG): expected found ليكوبار 40% SE ['Azoxystrobin', 'Propiconazole'], got cannot_verify  ; failed: product_ok, abstained
- `g2b-dev-008` [eg_exact] 'مستر جرين 1.8% EC' (EG): expected found مستر جرين 1.8% EC ['Abamectin (aka avermectin)'], got cannot_verify  ; failed: product_ok, abstained
