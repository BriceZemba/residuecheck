# Evaluation sets

All sets are built by scripts from committed data, with a fixed seed. 30% of each set is held out in `eval/heldout/` and not used while tuning; headline numbers are reported on held-out cases only.

## G1: regulatory lookup (120 cases)

Built by `python eval/build_g1.py` from the EU Pesticides Database snapshot of 2026-09-13 (`data/eu_snapshot/2026-09-13`). Seed 20260913. Files: `gold/g1_dev.jsonl` (83), `heldout/g1_heldout.jsonl` (37), `gold/g1_manifest.json`.

Each case is a question a compliance officer might ask, phrased with the names people use (EU English name, French residue name, lower case, or a crop synonym such as "Clementines" or "Pearl onions"):

```json
{"question": {"substance": "Acrinathrine", "crop": "Limes", "date": "2026-09-13", "destination": "EU"},
 "truth": {"eu_substance": "Acrinathrin", "eu_status": "Not approved", "crop_code": "0110040",
           "mrl_mg_per_kg": 0.01, "at_loq": true, "applies_from": "2024-08-12", "regulation": "...",
           "previous": "0.02 mg/kg (limit of quantification)", "verdict": "RED", "verdict_codes": ["MRL_AT_LOQ"]}}
```

| Stratum | Cases | What it tests |
|---|---|---|
| changed | 40 | Limit in force took effect on or after 2024-01-01 and differs from the previous one. Where memory-based answers go stale. |
| upcoming | 10 | A dated change after the snapshot; the question is dated 14 days after it takes effect. |
| loq_stable | 25 | Limit at the limit of quantification, unchanged since before 2024. |
| numeric_stable | 30 | Limit above quantification, unchanged since before 2024. |
| no_mrl_required | 5 | Substances exempt from limits (Annex IV). |
| unknown | 10 | Invented substance names, checked absent from the EU data. The right answer is "cannot verify". |

Verdict mix: 63 RED, 26 GREEN, 21 AMBER, 10 CANNOT_VERIFY. 74 distinct substances, 32 crops. 64 cases use substances that appear in real RASFF notifications or ONSSA products.

How the truth was checked: `tests/test_g1.py` re-derives every limit from the snapshot's raw version list (not the lookup function the builder used) and checks the builder reproduces the files byte for byte.

Limits of this set, stated plainly:

- The truth `verdict` comes from ResidueCheck's own rules (v0) applied to a label-compliant spray. For the full pipeline, which reads the same snapshot, G1 therefore tests name resolution and integration, not independent regulatory knowledge. It is an independent test for the `closed-book` and `tavily-only` configurations, which must find the numbers themselves.
- The `upcoming` stratum comes from only 3 substances (1,4-dimethylnaphthalene 4 cases, metribuzin 3, triclopyr 3), because few dated future changes exist for the 32 crops.
- Some crop synonyms are obscure (e.g. "Angled luffas" for Courgettes). They are kept as hard cases.
- Only single-residue substances are included; multi-residue substances (e.g. copper compounds) are not in G1.
