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

Verdict mix: 67 RED, 25 GREEN, 18 AMBER, 10 CANNOT_VERIFY. 69 distinct substances, 31 crops. 67 cases use substances that appear in real RASFF notifications or ONSSA products (list frozen in `gold/g1_relevant_substances.json`).

History (all before any model-based system was scored):

1. 2026-09-14: regenerated because the relevance weighting depended on the substance resolver, which had improved. The relevance list is now frozen so resolver changes cannot move the gold set.
2. 2026-09-14: regenerated after the first `rules-only` dev run exposed two builder defects: a French residue name with an HTML entity that also covered two substances (benalaxyl / benalaxyl-M), and a crop "synonym" that was a comma fragment ("not elsewhere mentioned"). French residue names are now unescaped, cut before brackets, and only used when the residue belongs to one substance; synonym fragments are skipped. `tests/test_eval_runner.py` scans every G1 and G2 question for these defects. Held-out cases were not opened; the scan is automated.

3. 2026-09-17: regenerated after fixing the substance -> residue join (EU residue ids and residue redefinitions are now followed, e.g. fosetyl -> phosphonic acid). Under the corrected join one held-out case linked to two residue definitions, which breaks G1's single-residue rule; rather than patch one case, the set was rebuilt with the corrected join. Only the changed fields of that case were inspected (residue ids, verdict), not its question.

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

## G3: spray-log photos (6 synthetic logs, real photos pending)

Built by `python eval/build_g3.py` (seed 20260919). Six handwritten-style treatment logs for citrus, rendered with Windows handwriting fonts on simulated ruled paper; each image says "SYNTHETIC TEST IMAGE" on the page. The content is realistic: real ONSSA citrus products with the dose and target pest from their own label, dates across the 2026 season, some names written in lower case, without a space, or misspelled ("ACTRA 25 WG"). Defects: none (log01), 4 degree tilt (log02), cursive font with blur and JPEG compression (log03), a crossed-out entry rewritten on the next line (log04), ink smudges hiding one date and one product (log05), and tilt, shadow, low contrast, mixed or year-less dates, a smudged dose and a crossed-out entry (log06). Truth: `g3/logNN.json` (rows with date, text as written, intended ONSSA product, dose, target, crossed_out, unreadable). Dev: log01-04 (27 lines), held-out: log05-06 (14 lines). The images are byte-identical on rebuild.

Scoring (`score_g3`): rows are matched best-first on product, date, dose and target. Reported: row recall, field accuracy (a product counts if it matches the text as written or the intended product), unreadable cells left empty (and flagged), guessed unreadable cells (must be 0), invented rows, crossed-out lines used as real sprays, and, when the system resolves products, how many resolve to the intended ONSSA product. A case passes with every line found, nothing invented, no crossed-out line used, no guessed cell and at least 90% field accuracy. An oracle answer passes all six (test).

What G3 cannot show yet: synthetic fonts are cleaner than real handwriting, so a good score here is necessary, not sufficient. Real photos go in `g3_real/` (instructions there, including consent and redaction) and are scored as stratum `real`. The parser (`residuecheck/logparse.py`) takes the vision model from `RESIDUECHECK_VISION_MODEL`; no model is chosen until spike S1 runs, so every configuration skips G3 for now. The parser's output is validated before use: flagged cells lose any value the model wrote, malformed dates become unreadable, and crossed-out or incomplete lines go to a review list instead of the check.

## G4: back-test on real EU rejections (564 RASFF notifications)

Built by `python eval/build_g4.py` (seed 20260916) from `data/rasff_pesticides_fv.csv`: 717 RASFF notifications (2024-01 to 2026-09) for pesticide residues in fruit and vegetables from Türkiye, Egypt, Kenya, India and Morocco. Product names were labelled by hand to the 32 supported crops (`labels/g4_labels.json`, 286 distinct names; frozen fruit keeps its fresh code because Annex I covers "fresh or frozen", chili peppers share the sweet pepper code). Skipped: 123 crops outside the 32 (vine leaves, drumsticks, guavas, pears...), 28 processed products (raisins, brined leaves, dried tomatoes, olives), 2 with no named substance. 564 cases: 395 dev, 169 held-out.

The question is what a log would give once products are resolved: crop, active substances, and the notification date as the EU arrival date. The truth has an independent part (the lot really was rejected or alerted, and RASFF marks some substances "unauthorised") and a part taken from the same EU snapshot as the rules (the limit in force on that date). Strata: `preventable` (481: at least one substance has a limit at quantification, or only the 0.01 mg/kg default, so any detectable residue fails and the log alone was enough to stop the lot), `dose_dependent` (57: limits above quantification; whether the lot failed depended on dose and timing, which a log check does not see) and `unknown_history` (26: the snapshot keeps only recent limit versions, and for these dates it has no value; the rules must not say GREEN).

So G4 measures how much of the real rejection record the rules would have caught before shipping. It does not measure prediction of measured residues, and the preventable share is circular with the rules for limit values.

Held-out, `rules-only`: 139/139 preventable lots blocked, 0 false greens, 68/68 RASFF-unauthorised substances flagged (63 RED, 4 AMBER because the EU keeps an import tolerance for them, e.g. spirotetramat on peppers, which is the correct reading, and 1 "cannot verify": phenthoate, see below), 18 of 25 dose-dependent lots got no warning. Overall 139/169 (82%) of real rejected lots would have been stopped at the log check.

The back-test found two rule gaps, both fixed before the one held-out run. They were found from dev rule failures and from a listing of substances without a limit that read the truth fields of all 564 cases, held-out included (no system answers on held-out were looked at): substances the EU database links only to the Art. 18(1)(b) default limit (tetramethrin, matrine, diafenthiuron) came back "cannot verify" instead of RED (new finding `MRL_DEFAULT`), and cadusafos was not joined to its residue because the substance is named "Cadusafos (aka ebufos)" (the residue join now also uses the name without its parenthetical; 757 substances linked, was 754). Phenthoate stays "cannot verify": it is listed in Annex III with no value for these crops, and the rules do not guess. G1 was protected from the join change: its candidate pool and residue ids are frozen in `gold/g1_pool_substances.json`, and the rebuilt files are byte-identical.

## G6: safe alternatives (19 citrus lots)

Built by `python eval/build_g6.py` from the ONSSA citrus crop index (`data/onssa_crops_index.json`, built with `scripts/onssa_crop_index.py`) and the EU snapshot. Each case: a Moroccan product registered for oranges or mandarins that is RED under EU rules (limit at the limit of quantification), a harvest date and an earliest spray date. The truth is the set of products the verifier accepts: registered for the crop, against the same pest, no shared active substance, pre-harvest interval fits, GREEN under the rules. Seed 20260918. Files: `gold/g6_dev.jsonl` (13), `heldout/g6_heldout.jsonl` (6).

What G6 can and cannot show: the truth comes from the same checks the verifier applies, so the deterministic planner is correct by construction and its score proves nothing. G6 is for the model configurations: `closed-book` (Nemotron from memory, no tools) and `full` (with tools) are scored on how many raw proposals are unsafe, whether they find a safe option when one exists, and `no-verifier` shows what would reach the user without the checks. A shown option also counts as unsafe if its spray date is past the product's latest spray date.

The citrus index (360 products for "Agrumes", "Agrumes: Clémentinier", "Agrumes: Oranger"; 340 pages fetched, 0 parse failures) yields only 19 distinct qualifying failing products, so the set has 19 cases instead of the planned 20. 16 cases have at least one safe option (up to 22), 3 have none. Three failing products are herbicides: the rules flag them because the EU limit on the fruit is at quantification, which is conservative when a herbicide is applied under the trees.

Baseline: `rules-only` (the deterministic planner) 13/13 on dev, by construction. `closed-book` and `no-verifier` are built and skip until Token Factory works.

## Runner

`python eval/run.py --suite g1|g2|g2b|g2s|g3|g4|g6 --config <config> [--split dev|heldout]` writes `results/<suite>_<config>_<split>.json` (every answer and score) and `.md` (metrics and every failure). `python eval/run.py --summary` rebuilds `results/README.md`. Held-out runs are logged in `results/heldout_runs.log`.

| Config | What | Runs now |
|---|---|---|
| `rules-only` | exact names only, rules engine; "cannot verify" for Türkiye/Egypt; no vision (skips G3) | yes |
| `rules-fuzzy` | + fuzzy ONSSA suggestions with a clear margin (deterministic resolver) | yes |
| `full` | resolver agent (Nemotron on Token Factory + Tavily) with verifier | skipped until `NEBIUS_API_KEY` works |
| `no-tavily` | `full` without web search | skipped until `NEBIUS_API_KEY` works |
| `closed-book` | Nemotron from memory, no tools, still verified (G6 only so far) | skipped until `NEBIUS_API_KEY` works |
| `no-verifier` | `full` with the verifier off (G6 only so far) | skipped until `NEBIUS_API_KEY` works |

G2 reports `right_first_suggestion` separately: asking the user with the correct first suggestion is safe, but it is not counted as resolving.
