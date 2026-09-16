# G2S / rules-only / dev

EU snapshot + ONSSA cache + crop map + rules engine; exact-name lookups only; no model, no web

Run 2026-09-16T21:14:26, code 849fd11-dirty, 12 cases, 0.1 s, cost $0.0000.

| Metric | Value |
|---|---|
| pass | 0/12 (0%) |
| confident_wrong | 0 |
| abstained | 12 |

| Stratum | Pass |
|---|---|
| family | 0/1 (0%) |
| single | 0/11 (0%) |

## Failures (12)

- `g2s-dev-001` '(E,E) 8,10-dodécadien-1-ol': expected (E,E)-8,10-Dodecadien-1-ol (SCLP Alcohols), got cannot_verify None; 
- `g2s-dev-002` '1-Dodecanol': expected Dodecan-1-ol (SCLP Alcohols), got cannot_verify None; 
- `g2s-dev-003` '1-Tetradecanol': expected Tetradecan-1-ol (SCLP Alcohols), got cannot_verify None; 
- `g2s-dev-004` 'Cuivre - oxychlorure de cuivre': expected Copper oxychloride, got cannot_verify None; 
- `g2s-dev-005` 'Cuivre - sulfate de cuivre': expected Copper compounds, got cannot_verify None; 
- `g2s-dev-006` 'Cuivre - sulfate tétracuivrique tricalcique': expected Bordeaux mixture, got cannot_verify None; 
- `g2s-dev-007` 'Fosétyl-Aluminium': expected Fosetyl, got cannot_verify None; 
- `g2s-dev-008` "Glyphosate -sel d'isopropylamine": expected Glyphosate, got cannot_verify None; 
- `g2s-dev-009` 'Huile minérale paraffinique': expected Paraffin oil, got cannot_verify None; 
- `g2s-dev-010` 'Hydrolysat de protéines': expected Hydrolysed proteins, got cannot_verify None; 
- `g2s-dev-011` 'Propamocarbe HCl': expected Propamocarb, got cannot_verify None; 
- `g2s-dev-012` 'Pyrèthre': expected Pyrethrins, got cannot_verify None; 
