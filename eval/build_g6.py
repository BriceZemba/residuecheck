"""Build eval set G6 (safe alternatives): 20 citrus lots where a registered Moroccan product fails EU rules.

For each case: a failing product (registered for the crop in Morocco, but RED under EU rules because its limit on
the crop is at the limit of quantification), a crop (oranges or mandarins), a harvest date and an earliest spray
date. The truth is the set of products the verifier accepts (residuecheck/alternatives.py `safe_set`): registered for
the crop, against the same pest, no shared active substance, pre-harvest interval fits, GREEN under the rules.

Because the truth comes from the same checks the verifier applies, G6 does not test the deterministic planner (it is
correct by construction). It measures model-based configurations: how many of their raw proposals are unsafe, whether
they find a safe option when one exists, and what reaches the user when the verifier is switched off.

Needs data/onssa_crops_index.json (scripts/onssa_crop_index.py for the citrus crop names).
Usage: python eval/build_g6.py
"""
import datetime
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.alternatives import Alternatives, _load_record  # noqa: E402
from residuecheck.eu_data import Snapshot  # noqa: E402
from residuecheck.rules import Level  # noqa: E402

SEED = 20260918
TARGET = 20  # the citrus index yields 19 distinct qualifying products, so the set has 19 cases
HELDOUT = 6
CROPS = {"0110020": "Oranges", "0110050": "Mandarins"}
HARVESTS = ["2026-11-20", "2026-12-15", "2027-01-20", "2027-03-01"]
LEAD_DAYS = (7, 60)  # earliest spray date = harvest minus this many days
OUT_DEV = ROOT / "eval" / "gold" / "g6_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g6_heldout.jsonl"
OUT_MANIFEST = ROOT / "eval" / "gold" / "g6_manifest.json"


def failing_products(alt, eu, crop_code, harvest):
    """Registered for the crop, pests known, and RED because of an EU limit (not because of the spray date)."""
    out = []
    for name in alt.candidate_names(crop_code):
        rec = _load_record(name)
        if not rec or not rec.get("substances"):
            continue
        opt = alt.describe(rec, crop_code, harvest)
        if opt is None or not opt.pests or not isinstance(opt.dar_days, int):
            continue
        spray = harvest - datetime.timedelta(max(opt.dar_days, 1) + 30)  # interval clearly respected
        verdict, reasons = alt.check(rec, crop_code, spray, harvest)
        if verdict == Level.RED and any(r.startswith("MRL_AT_LOQ") for r in reasons):
            out.append(rec["trade_name"])
    return sorted(out)


def main():
    eu = Snapshot("2026-09-13")
    alt = Alternatives(eu)
    rng = random.Random(SEED)
    pools = {code: failing_products(alt, eu, code, datetime.date(2026, 12, 15)) for code in CROPS}
    pairs = [(code, name) for code, names in pools.items() for name in names]
    rng.shuffle(pairs)
    cases, used = [], set()
    for code, name in pairs:
        if len(cases) >= TARGET or name in used:
            continue
        harvest = datetime.date.fromisoformat(rng.choice(HARVESTS))
        not_before = harvest - datetime.timedelta(rng.randint(*LEAD_DAYS))
        failing = _load_record(name)
        verdict, reasons = alt.check(failing, code, not_before, harvest)
        if verdict != Level.RED:
            continue
        safe = alt.safe_set(name, code, harvest, not_before)
        cands, pests, _ = alt.candidates(failing, code, harvest, not_before)
        latest = {o.product: o.latest_spray.isoformat() for _, o in cands if o.product in safe}
        used.add(name)
        cases.append({"question": {"failing_product": name, "crop_code": code, "crop": CROPS[code],
                                   "harvest_on": harvest.isoformat(), "not_before": not_before.isoformat()},
                      "truth": {"safe_products": safe, "latest_spray": latest, "has_safe_option": bool(safe), "candidates_registered": len(cands),
                                "failing_codes": sorted({r.split(":")[0] for r in reasons}),
                                "target_pests": sorted(pests)},
                      "stratum": "has_option" if safe else "no_option"})
    order = list(range(len(cases)))
    rng.shuffle(order)
    held = set(order[:HELDOUT])
    dev = [c for i, c in enumerate(cases) if i not in held]
    heldout = [c for i, c in enumerate(cases) if i in held]
    for split, rows, path in (("dev", dev, OUT_DEV), ("heldout", heldout, OUT_HELDOUT)):
        rows.sort(key=lambda c: (c["question"]["crop_code"], c["question"]["failing_product"]))
        path.write_text("".join(json.dumps({"id": f"g6-{split}-{i + 1:03d}", "split": split, "stratum": c["stratum"],
                                            "question": c["question"], "truth": c["truth"]}, ensure_ascii=False) + "\n"
                                for i, c in enumerate(rows)), encoding="utf-8", newline="\n")
    manifest = {"seed": SEED, "total": len(cases), "dev": len(dev), "heldout": len(heldout),
                "failing_pool": {code: len(v) for code, v in pools.items()},
                "strata": {s: sum(c["stratum"] == s for c in cases) for s in ("has_option", "no_option")},
                "safe_set_size": {"min": min(len(c["truth"]["safe_products"]) for c in cases),
                                  "max": max(len(c["truth"]["safe_products"]) for c in cases)},
                "index": "data/onssa_crops_index.json", "snapshot": "2026-09-13"}
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
