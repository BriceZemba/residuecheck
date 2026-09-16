# G2S / rules-only / dev

EU snapshot + ONSSA cache + crop map + rules engine; exact-name lookups only; no model, no web

Run 2026-09-16T21:29:56, code 7c2bf8c-dirty, 23 cases, 0.1 s, cost $0.0000.

| Metric | Value |
|---|---|
| pass | 1/23 (4%) |
| confident_wrong | 0 |
| abstained | 23 |

| Stratum | Pass |
|---|---|
| family | 0/1 (0%) |
| group_residue | 0/2 (0%) |
| no_eu_substance | 1/1 (100%) |
| single | 0/19 (0%) |

## Failures (22)

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
- `g2s-dev-013` 'Clodinafop-propargyl': expected Clodinafop, got cannot_verify None; 
- `g2s-dev-014` 'Emamectin benzoate': expected Emamectin, got cannot_verify None; 
- `g2s-dev-015` 'Acide oléique': expected Oleic acid  (CAS 112-80-1), got cannot_verify None; 
- `g2s-dev-016` 'Cléthodime': expected Clethodim, got cannot_verify None; 
- `g2s-dev-018` 'Florasulame': expected Florasulam, got cannot_verify None; 
- `g2s-dev-019` 'Fluazifop-p-butyl': expected Fluazifop-P, got cannot_verify None; 
- `g2s-dev-020` 'Glyphosate-potassium salt': expected Glyphosate, got cannot_verify None; 
- `g2s-dev-021` 'Iodosulfuron-méthyl-sodium': expected Iodosulfuron, got cannot_verify None; 
- `g2s-dev-022` 'Pyrimiphos-méthyl': expected Pirimiphos-methyl, got cannot_verify None; 
- `g2s-dev-023` 'chlorpyriphos-ethyl': expected Chlorpyrifos, got cannot_verify None; 
