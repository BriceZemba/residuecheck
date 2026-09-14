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

Verdict mix: 64 RED, 20 GREEN, 26 AMBER, 10 CANNOT_VERIFY. 74 distinct substances, 32 crops. 67 cases use substances that appear in real RASFF notifications or ONSSA products (list frozen in `gold/g1_relevant_substances.json`).

History (both before any model-based system was scored):

1. 2026-09-14: regenerated because the relevance weighting depended on the substance resolver, which had improved. The relevance list is now frozen so resolver changes cannot move the gold set.
2. 2026-09-14: regenerated after the first `rules-only` dev run exposed two builder defects: a French residue name with an HTML entity that also covered two substances (benalaxyl / benalaxyl-M), and a crop "synonym" that was a comma fragment ("not elsewhere mentioned"). French residue names are now unescaped, cut before brackets, and only used when the residue belongs to one substance; synonym fragments are skipped. `tests/test_eval_runner.py` scans every G1 and G2 question for these defects. Held-out cases were not opened; the scan is automated.

`tests/test_g1.py` checks the builder reproduces the committed files byte for byte.

## G2: trade-name resolution, Morocco (60 cases)

Built by `python eval/build_g2.py` from the ONSSA index phytosanitaire (product list saved in `data/onssa_products_2026-09-14.json`, product pages cached in `data/onssa_cache/`). Seed 20260914. Files: `gold/g2_dev.jsonl` (42), `heldout/g2_heldout.jsonl` (18), `gold/g2_manifest.json`.

Truth comes from ONSSA records only, independent of the EU snapshot and the rules engine: product name, active substances as ONSSA writes them, registration for the lot's crop (through `data/crop_map_onssa.json`), and the pre-harvest interval.

| Stratum | Cases | What it tests |
|---|---|---|
| exact | 40 | Real products drawn at random; 28 on a crop they are registered for, 12 on a crop they are not |
| variant | 10 | Real products written the way logs get written: letter swaps (C/K), digit/letter confusion (O/0, I/1), a dropped letter, a missing formulation code. None is resolvable by exact normalised matching |
| fake | 10 | Invented names with no exact or close (difflib 0.7) match in the index. Two first candidates turned out to be near real products (OXYMAR 50 WP, NOVACRID) and were replaced |

The EU name of each substance is deliberately not part of G2 truth: the deterministic resolver cannot resolve 12 of the 44 distinct substance names (copper salts, "Glyphosate -sel d'isopropylamine", pheromone alcohols, "Pyrèthre", mineral oil, protein hydrolysate), so storing its output would bake its errors into the set. Scoring the EU mapping needs a hand-checked alias set (planned).

Limits: Morocco only; the crop registration truth depends on the hand-written crop map.

## Runner

`python eval/run.py --suite g1|g2 --config rules-only [--split dev|heldout]` writes `results/<suite>_<config>_<split>.json` (every answer and score) and `.md` (metrics and every failure). `python eval/run.py --summary` rebuilds `results/README.md`. Held-out runs are logged in `results/heldout_runs.log`. Model-based configs (`closed-book`, `tavily-only`, `full`) exit with "skipped" until the API keys are set.

How the truth was checked: `tests/test_g1.py` re-derives every limit from the snapshot's raw version list (not the lookup function the builder used) and checks the builder reproduces the files byte for byte.

Limits of this set, stated plainly:

- The truth `verdict` comes from ResidueCheck's own rules (v0) applied to a label-compliant spray. For the full pipeline, which reads the same snapshot, G1 therefore tests name resolution and integration, not independent regulatory knowledge. It is an independent test for the `closed-book` and `tavily-only` configurations, which must find the numbers themselves.
- The `upcoming` stratum comes from only 3 substances (1,4-dimethylnaphthalene 4 cases, metribuzin 3, triclopyr 3), because few dated future changes exist for the 32 crops.
- Some crop synonyms are obscure (e.g. "Angled luffas" for Courgettes). They are kept as hard cases.
- Only single-residue substances are included; multi-residue substances (e.g. copper compounds) are not in G1.
