"""Build eval set G1 (regulatory lookup): 120 cases of "substance x EU crop x date" with ground truth
taken from the frozen EU snapshot.

What G1 measures: whether a system states the right EU limit, approval status and regulatory verdict for
a question phrased the way people write it (English or French substance names, crop names or synonyms).
Ground truth is deterministic from the snapshot. For the full ResidueCheck pipeline the lookup itself uses
the same snapshot, so G1 mainly tests name resolution and integration there; it is a real test for the
closed-book and Tavily-only configurations. The README says so.

Strata (target counts):
  changed          40  limit in force on the snapshot date took effect on or after 2024-01-01 and differs from the previous one
  upcoming         10  a dated change after the snapshot date; question dated 14 days after it takes effect
  loq_stable       25  limit at LOQ, unchanged since before 2024, nothing scheduled
  numeric_stable   30  limit above LOQ, unchanged since before 2024, nothing scheduled
  no_mrl_required   5  Annex IV substance
  unknown          10  invented substance names (checked absent from the EU database): expected CANNOT_VERIFY

Split: 30% of each stratum goes to eval/heldout/ (fixed seed). Held-out cases are not looked at while tuning.
Substances seen in RASFF notifications or the ONSSA cache are preferred (2 of 3 picks when available).

Usage: python eval/build_g1.py
"""
import csv
import datetime
import html
import json
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.eu_data import Snapshot, base_name, norm_residue  # noqa: E402
from residuecheck.rules import Application, Lot, evaluate  # noqa: E402

SEED = 20260913
SNAPSHOT = "2026-09-13"
CHANGE_CUTOFF = datetime.date(2024, 1, 1)
TARGETS = {"changed": 40, "upcoming": 10, "loq_stable": 25, "numeric_stable": 30, "no_mrl_required": 5, "unknown": 10}
HELDOUT_SHARE = 0.3
MAX_CASES_PER_SUBSTANCE = 3
INVENTED_NAMES = ["Fluvaprotin", "Tetraconazamid", "Pyrozanil", "Chlorbenfurone", "Dimetrazolin",
                  "Spirocarbamide", "Oxathiapyrine", "Benzopyridamil", "Cyflumetrazine", "Metoxafenol"]
OUT_DEV = ROOT / "eval" / "gold" / "g1_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g1_heldout.jsonl"
OUT_MANIFEST = ROOT / "eval" / "gold" / "g1_manifest.json"
POOL_FILE = ROOT / "eval" / "gold" / "g1_pool_substances.json"


def clean_product_name(name):
    return re.sub(r"^\(?[a-z]\)\s*", "", name or "").strip()


RELEVANT_FILE = ROOT / "eval" / "gold" / "g1_relevant_substances.json"


def relevant_substance_ids(eu):
    """Substances seen in RASFF or ONSSA data. Frozen to a file on first build so later resolver changes
    (which resolve more names) cannot silently change the gold set."""
    if RELEVANT_FILE.exists():
        return set(json.loads(RELEVANT_FILE.read_text(encoding="utf-8"))["substance_ids"])
    ids = set()
    with (ROOT / "data" / "rasff_pesticides_fv.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = eu.substance(row["substance"])
            if s:
                ids.add(s["substance_id"])
    for path in (ROOT / "data" / "onssa_cache").glob("*.json"):
        for sub in json.loads(path.read_text(encoding="utf-8")).get("substances", []):
            s = eu.substance(sub["name_fr"])
            if s:
                ids.add(s["substance_id"])
    RELEVANT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RELEVANT_FILE.write_text(json.dumps({"frozen": "2026-09-14", "from": ["data/rasff_pesticides_fv.csv", "data/onssa_cache/*.json"],
                                         "substance_ids": sorted(ids)}, indent=1) + "\n", encoding="utf-8", newline="\n")
    return ids


def frozen_join(eu):
    """Substance -> residue id for substances with a single linked residue, and how many substances share each
    residue. Frozen to a file on first build: later improvements to the substance-to-residue join (e.g. the
    base-name join of 2026-09-16) must not reshuffle the dev/held-out split or the question wording."""
    if POOL_FILE.exists():
        data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        return ({int(k): v for k, v in data["single_residue"].items()},
                {int(k): v for k, v in data["residue_owners"].items()})
    single, owners = {}, {}
    for sub in eu.substances:
        rids = eu.residue_ids(sub)
        if len(rids) == 1:
            single[sub["substance_id"]] = rids[0]
        for rid in rids:
            owners[rid] = owners.get(rid, 0) + 1
    POOL_FILE.write_text(json.dumps({"frozen": "2026-09-16", "single_residue": {str(k): single[k] for k in sorted(single)},
                                     "residue_owners": {str(k): owners[k] for k in sorted(owners)}}, indent=0) + "\n",
                         encoding="utf-8", newline="\n")
    return single, owners


def candidates(eu):
    """Every (substance, residue, crop) with a single linked residue, grouped by stratum."""
    pools = {k: [] for k in TARGETS if k != "unknown"}
    single, _ = frozen_join(eu)
    for sub in eu.substances:
        rid = single.get(sub["substance_id"])
        if rid is None:
            continue
        for crop in sorted(eu.crops):
            versions = eu.mrl_versions(rid, crop)
            if not versions:
                continue
            current = eu.mrl_on(rid, crop, eu.date)
            later = eu.scheduled_after(rid, crop, eu.date)
            if current is None:
                continue
            prev = eu.previous(current)
            base = {"substance": sub, "residue_id": rid, "crop": crop}
            if current.no_mrl_required:
                if not later:
                    pools["no_mrl_required"].append({**base, "date": eu.date})
                continue
            if current.applies_from >= CHANGE_CUTOFF and prev is not None:
                pools["changed"].append({**base, "date": eu.date})
            elif current.applies_from < CHANGE_CUTOFF and not later:
                pools["loq_stable" if current.at_loq else "numeric_stable"].append({**base, "date": eu.date})
            for nxt in later:
                if nxt.value != current.value or nxt.at_loq != current.at_loq:
                    pools["upcoming"].append({**base, "date": nxt.applies_from + datetime.timedelta(14)})
                    break
    return pools


def pick(pool, n, relevant, rng, per_substance):
    rng.shuffle(pool)
    rel = [c for c in pool if c["substance"]["substance_id"] in relevant]
    other = [c for c in pool if c["substance"]["substance_id"] not in relevant]
    chosen, pairs = [], set()

    def take(source, limit, cap=MAX_CASES_PER_SUBSTANCE):
        for c in source:
            if len(chosen) >= limit:
                return
            sid = c["substance"]["substance_id"]
            key = (sid, c["crop"])
            if key in pairs or per_substance.get(sid, 0) >= cap:
                continue
            chosen.append(c)
            pairs.add(key)
            per_substance[sid] = per_substance.get(sid, 0) + 1

    take(rel, round(n * 2 / 3))
    take(other, n)
    take(rel, n)  # top up if the general pool ran short
    take(pool, n, cap=len(pool))  # small strata (few substances): allow more than the cap, pairs stay unique
    return chosen


def phrase(eu, case, rng, residue_owners):
    sub, crop = case["substance"], eu.products[case["crop"]]
    fr_residue = html.unescape((eu.residue_names.get(str(case["residue_id"])) or {}).get("FR") or "")
    fr_short = re.split(r"[,([]", fr_residue)[0].strip()
    roll = rng.random()
    # A French residue name is only a fair question when that residue belongs to this one substance
    # (e.g. the benalaxyl residue covers benalaxyl and benalaxyl-M, so its name cannot identify either).
    if roll < 0.25 and fr_short and residue_owners.get(case["residue_id"]) == 1:
        substance_text = fr_short
    elif roll < 0.5 and base_name(sub["substance_name"]):
        substance_text = base_name(sub["substance_name"])
    else:
        substance_text = re.sub(r"\s*\(aka .*\)$", "", sub["substance_name"]).strip()
    # Synonym entries look like "Summer squashes/zucchini/pattypan squashes"; keep the first form. Entries can
    # themselves contain commas ("Other hybrids of Citrus reticulata, not elsewhere mentioned"), so splitting on
    # commas leaves fragments; real names start with a capital letter, fragments and "Other ..." entries are skipped.
    synonyms = sorted({s.split("/")[0].strip() for s in (crop.get("synonyms") or "").split(",")
                       if s.strip()[:1].isupper() and not s.strip().lower().startswith("other")
                       and "elsewhere" not in s.lower()})
    roll = rng.random()
    if roll < 0.25 and synonyms:
        crop_text = rng.choice(synonyms)
    elif roll < 0.5 and crop.get("FR"):
        crop_text = clean_product_name(crop["FR"])
    else:
        crop_text = clean_product_name(crop["EN"])
    return substance_text, crop_text


def truth(eu, case):
    sub, rid, crop, date = case["substance"], case["residue_id"], case["crop"], case["date"]
    m = eu.mrl_on(rid, crop, date)
    prev = eu.previous(m)
    lot = Lot(crop, date - datetime.timedelta(10), [Application(sub["substance_name"], date - datetime.timedelta(40),
                                                                [sub["substance_name"]], True, 0)], arrival_on=date)
    result = evaluate(lot, eu)
    return {
        "eu_substance": sub["substance_name"], "substance_id": sub["substance_id"], "eu_status": sub["substance_status"],
        "residue_id": rid, "residue": m.residue_name, "crop_code": crop, "crop": eu.crops[crop],
        "mrl_mg_per_kg": m.value, "at_loq": m.at_loq, "no_mrl_required": m.no_mrl_required,
        "applies_from": m.applies_from.isoformat(), "regulation": m.regulation, "regulation_url": m.regulation_url,
        "previous": prev.describe() if prev else None,
        "previous_from": prev.applies_from.isoformat() if prev else None,
        "verdict": result.verdict.name,
        "verdict_codes": sorted({f.code for f in result.findings if f.level > 0 and f.code != "SNAPSHOT_OLDER_THAN_ARRIVAL"}),
    }


def main():
    eu = Snapshot(SNAPSHOT)
    rng = random.Random(SEED)
    relevant = relevant_substance_ids(eu)
    pools = candidates(eu)
    _, residue_owners = frozen_join(eu)
    per_substance, cases = {}, []
    for stratum, n in TARGETS.items():
        if stratum == "unknown":
            continue
        for c in pick(pools[stratum], n, relevant, rng, per_substance):
            substance_text, crop_text = phrase(eu, c, rng, residue_owners)
            cases.append({"stratum": stratum, "question": {"substance": substance_text, "crop": crop_text,
                                                           "date": c["date"].isoformat(), "destination": "EU"},
                          "truth": truth(eu, c), "relevant_substance": c["substance"]["substance_id"] in relevant})

    crops = sorted(eu.crops)
    for name in INVENTED_NAMES:
        assert eu.substance(name) is None and norm_residue(name) not in eu._by_key, f"{name} exists in the EU data"
        crop = rng.choice(crops)
        cases.append({"stratum": "unknown", "question": {"substance": name, "crop": clean_product_name(eu.products[crop]["EN"]),
                                                          "date": eu.date.isoformat(), "destination": "EU"},
                      "truth": {"eu_substance": None, "crop_code": crop, "verdict": "CANNOT_VERIFY",
                                "verdict_codes": ["SUBSTANCE_UNRESOLVED"], "note": "Invented name, absent from the EU database"},
                      "relevant_substance": False})

    dev, heldout = [], []
    for stratum in TARGETS:
        group = [c for c in cases if c["stratum"] == stratum]
        rng.shuffle(group)
        k = round(len(group) * HELDOUT_SHARE)
        heldout += group[:k]
        dev += group[k:]
    for split, rows in (("dev", dev), ("heldout", heldout)):
        for i, c in enumerate(sorted(rows, key=lambda c: (list(TARGETS).index(c["stratum"]), c["question"]["substance"].lower(), c["truth"]["crop_code"]))):
            c["id"] = f"g1-{split}-{i + 1:03d}"
            c["split"] = split
    OUT_DEV.parent.mkdir(parents=True, exist_ok=True)
    OUT_HELDOUT.parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((OUT_DEV, dev), (OUT_HELDOUT, heldout)):
        rows.sort(key=lambda c: c["id"])
        path.write_text("".join(json.dumps({"id": c["id"], "split": c["split"], **{k: v for k, v in c.items() if k not in ("id", "split")}},
                                           ensure_ascii=False) + "\n" for c in rows), encoding="utf-8", newline="\n")

    counts = {s: {"available": len(pools.get(s, [])) if s != "unknown" else len(INVENTED_NAMES), "target": n,
                  "dev": sum(c["stratum"] == s for c in dev), "heldout": sum(c["stratum"] == s for c in heldout)}
              for s, n in TARGETS.items()}
    verdicts = {}
    for c in cases:
        verdicts[c["truth"]["verdict"]] = verdicts.get(c["truth"]["verdict"], 0) + 1
    manifest = {"snapshot": SNAPSHOT, "seed": SEED, "heldout_share": HELDOUT_SHARE, "total": len(cases),
                "dev": len(dev), "heldout": len(heldout), "strata": counts, "verdicts": verdicts,
                "relevant_substance_cases": sum(c["relevant_substance"] for c in cases),
                "distinct_substances": len({c["truth"]["eu_substance"] for c in cases if c["truth"]["eu_substance"]}),
                "distinct_crops": len({c["truth"]["crop_code"] for c in cases}),
                "verdict_source": "residuecheck.rules v0 on a label-compliant application (registered, DAR met), arrival on the question date"}
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
