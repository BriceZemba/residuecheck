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

## G2b: trade-name resolution, Türkiye and Egypt (15 cases)

Built by `python eval/build_g2b.py`. Truth is fetched directly from the official register product pages (BKÜ `bku.tarimorman.gov.tr/BKURuhsat/Details/{id}`, APC `www.apc.gov.eg/ar/PesticideDetails.aspx?id={id}`), never through Tavily, and cached in `data/registers_cache/`. Seed 20260916. Files: `gold/g2b_dev.jsonl` (10), `heldout/g2b_heldout.jsonl` (5).

| Stratum | Cases | What it tests |
|---|---|---|
| tr_exact | 6 | Currently licensed Turkish products (validity date after 2026-09-16), name as on the register |
| eg_exact | 6 | Registered Egyptian products ("مسجل"), Arabic trade name as on the register |
| fake | 3 | Invented names (1 Latin, 2 Arabic); a domain-restricted Tavily search found no page with them |

Kept only products whose every active substance maps to an EU database name, so the substance part of the answer can be scored; technical-grade imports (Arabic "خام", TEKNİK) are excluded because growers do not spray them. Egyptian product IDs are sparse: 124 pages fetched for 6 usable products. Scored as: the product is confirmed (`resolved`, not merely suggested), the name matches, and the EU substances match exactly. Without the resolver agent the only possible answer is "cannot verify" (baseline 2/10 on dev, the fakes).

## G2s: substance-name resolution (33 cases)

Built by `python eval/build_g2s.py` from `gold/g2s_seed.json` (12 names, all dev) and `labels/g2s_batch2.json` (21 names; 10 held out with seed 20260917). Files: `gold/g2s_dev.jsonl` (23), `heldout/g2s_heldout.jsonl` (10).

The pool is every substance name in the ONSSA cache, the Türkiye/Egypt register cache and the RASFF export that the deterministic resolver cannot map. Each name was labelled by hand against EU database names (checked to exist). Strata: `single` (one EU name), `group_residue` (any substance with the same residue definition is right, e.g. copper forms, dithiocarbamates, carbendazim/benomyl, 2-chloroethanol under ethylene oxide), `family` (paraffin oil: right only as "needs confirmation" because the CAS number decides), `no_eu_substance` (a safener and an adjuvant: the right answer is to refuse).

Rule, recorded because the held-out names were seen while labelling: the deterministic resolver's aliases and ending rules must not be extended using names from `labels/g2s_batch2.json`. Baseline without a model: 1/23 on dev (the refusal case).

## Runner

`python eval/run.py --suite g1|g2|g2b|g2s --config <config> [--split dev|heldout]` writes `results/<suite>_<config>_<split>.json` (every answer and score) and `.md` (metrics and every failure). `python eval/run.py --summary` rebuilds `results/README.md`. Held-out runs are logged in `results/heldout_runs.log`.

| Config | What | Runs now |
|---|---|---|
| `rules-only` | exact names only, rules engine; "cannot verify" for Türkiye/Egypt | yes |
| `rules-fuzzy` | + fuzzy ONSSA suggestions with a clear margin (deterministic resolver) | yes |
| `full` | resolver agent (Nemotron on Token Factory + Tavily) with verifier | skipped until `NEBIUS_API_KEY` works |
| `no-tavily` | `full` without web search | skipped until `NEBIUS_API_KEY` works |
| `closed-book`, `no-verifier` | planned | not built |

G2 reports `right_first_suggestion` separately: asking the user with the correct first suggestion is safe, but it is not counted as resolving.
