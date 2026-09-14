"""Build eval set G2 (trade-name resolution, Morocco): 60 cases of "trade name x crop" with truth from the
official ONSSA index phytosanitaire.

What G2 measures: can a system go from the product name written in a spray log to the active substances,
whether the product is registered for the lot's crop, and the pre-harvest interval. Truth is independent of
the EU snapshot and of the rules engine: it comes from ONSSA records (cached in data/onssa_cache/).

Strata:
  exact    40  real product, name written as in the index; 70% on a registered crop, 30% on a crop it is not registered for
  variant  10  real product, name written the way logs get written (no spaces, lower case, OCR-like letter/digit swaps,
               missing formulation code). Expected: resolve to the right product, or ask; never resolve to a wrong one
  fake     10  invented names, checked absent from the index with no close match. Expected: not found

Products are drawn at random (fixed seed) from the full trade-name list, keeping those with at least one field
usage on a crop in the EU snapshot. Split: 30% of each stratum to eval/heldout/.

Needs network on first run (ONSSA list + product pages, ~2 s per product with a politeness delay). Re-runs use
data/onssa_products_2026-09-14.json and the cache.

Usage: python eval/build_g2.py
"""
import datetime
import difflib
import json
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.crops import load_map, registration  # noqa: E402
from residuecheck.eu_data import Snapshot  # noqa: E402
from residuecheck.onssa import CACHE, URL, Onssa, norm  # noqa: E402

SEED = 20260914
SNAPSHOT = "2026-09-13"
LIST_FILE = ROOT / "data" / "onssa_products_2026-09-14.json"
TARGETS = {"exact": 40, "variant": 10, "fake": 10}
NOT_REGISTERED_SHARE = 0.3
HELDOUT_SHARE = 0.3
MAX_FETCH = 160
# Checked against the ONSSA list of 2026-09-14: no exact match and no close match at cutoff 0.7.
# ("OXYMAR 80 WG" and "NOVACIDE 18 EC" were dropped: OXYMAR 50 WP and NOVACRID are real products.)
FAKE_NAMES = ["ZORBEX 300 SC", "PHYTOLIX 25 EC", "KARMITAL 40 WG", "DRAMOTEX 20 SL", "TERRAFOSS 50 WP",
              "BLUMIFOR 60 WG", "VERIDEX 10 SL", "ATLAZINE 500 SC", "SOUSSIFOL 72 WP", "GHARBOMYL 5 EC"]
OUT_DEV = ROOT / "eval" / "gold" / "g2_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g2_heldout.jsonl"
OUT_MANIFEST = ROOT / "eval" / "gold" / "g2_manifest.json"


def load_onssa():
    if LIST_FILE.exists():
        return Onssa(list_file=LIST_FILE)
    o = Onssa()
    o.load_list()
    o.save_list(LIST_FILE, datetime.date(2026, 9, 14).isoformat())
    return o


def field_crops(record, eu, crop_map):
    """Snapshot crops the product is registered for (field use), and snapshot crops it is clearly not registered for."""
    registered, not_registered = {}, []
    for code in sorted(eu.crops):
        r = registration(record, code, eu, crop_map)
        if r.status in ("registered", "registered_narrower"):
            registered[code] = r
        elif r.status == "not_registered":
            not_registered.append(code)
    return registered, not_registered


def make_variant(name, all_norms, rng):
    """A realistic mis-writing of `name` that does not exactly match any real product name."""
    transforms = [
        lambda n: re.sub(r"\s+\d[\d,.]*\s*(EC|SC|WG|WP|SL|SG|EW|OD|CS|ME|DP|GR|WDG|ZC|SE)\b.*$", "", n, flags=re.I),
        lambda n: n.replace(" ", ""),
        lambda n: n.lower(),
        lambda n: n.replace("C", "K", 1) if "C" in n else n.replace("K", "C", 1),
        lambda n: n.replace("O", "0", 1) if "O" in n else n.replace("I", "1", 1),
        lambda n: n[:len(n) // 2] + n[len(n) // 2 + 1:],  # one letter dropped
    ]
    kinds = ["formulation_dropped", "spaces_removed", "lower_case", "c_k_swap", "o_zero_swap", "letter_dropped"]
    order = list(range(len(transforms)))
    rng.shuffle(order)
    # Prefer writings an exact normalised lookup cannot resolve; case/space changes are only a fallback.
    for i in order:
        v = transforms[i](name).strip()
        if v and norm(v) != norm(name) and norm(v) not in all_norms:
            return v, kinds[i]
    for i in order:
        v = transforms[i](name).strip()
        if v and v != name and norm(v) == norm(name):
            return v, kinds[i]
    return None, None


def truth_for(record, code, reg, eu):
    # Truth is what ONSSA says. The EU name of each substance is NOT truth here: our deterministic resolver
    # misses many French label names (e.g. "Boscalide"), so storing its output would bake its errors into the set.
    subs = [{"name_fr": s["name_fr"], "content": s["content"]} for s in record["substances"]]
    return {"status": "found", "onssa_trade_name": record["trade_name"], "registration_no": record.get("registration_no"),
            "valid_until": record.get("valid_until"), "substances": subs, "crop_code": code, "crop": eu.crops[code],
            "registration_status": reg.status, "registered_for_crop": reg.registered_for_crop, "dar_days": reg.dar_days,
            "matched_usages": sorted({u["crop_fr"] for u in reg.matched_usages}), "source": URL,
            "retrieved": record.get("retrieved"), "index_updated": record.get("index_updated")}


def main():
    eu = Snapshot(SNAPSHOT)
    crop_map = load_map()
    onssa = load_onssa()
    rng = random.Random(SEED)
    names = sorted(onssa.names())
    all_norms = {norm(n) for n in names}
    rng.shuffle(names)

    qualified, fetched = [], 0
    need = TARGETS["exact"] + TARGETS["variant"]
    for name in names:
        if len(qualified) >= need or fetched >= MAX_FETCH:
            break
        cached = (CACHE / f"{norm(name)}.json").exists()
        if not cached:
            if onssa.list_html is None:
                onssa.load_list()
            fetched += 1
        rec = onssa.lookup(name)
        if rec.get("status") not in ("found",) and not rec.get("from_cache"):
            continue
        if not rec.get("substances"):
            continue
        registered, not_registered = field_crops(rec, eu, crop_map)
        if registered:
            qualified.append((rec, registered, not_registered))

    cases = []
    exact, variants = qualified[:TARGETS["exact"]], qualified[TARGETS["exact"]:need]
    n_not_registered = round(TARGETS["exact"] * NOT_REGISTERED_SHARE)
    for i, (rec, registered, not_registered) in enumerate(exact):
        if i < n_not_registered and not_registered:
            code = rng.choice(not_registered)
            reg = registration(rec, code, eu, crop_map)
        else:
            code = rng.choice(sorted(registered))
            reg = registered[code]
        cases.append({"stratum": "exact", "question": {"trade_name": rec["trade_name"], "crop": eu.crops[code], "country": "MA"},
                      "truth": truth_for(rec, code, reg, eu)})
    for rec, registered, _ in variants:
        v, how = make_variant(rec["trade_name"], all_norms, rng)
        code = rng.choice(sorted(registered))
        truth = truth_for(rec, code, registered[code], eu)
        truth["variant_of"], truth["variant_kind"] = rec["trade_name"], how
        truth["resolvable_by_exact_normalised_match"] = norm(v) == norm(rec["trade_name"])
        cases.append({"stratum": "variant", "question": {"trade_name": v, "crop": eu.crops[code], "country": "MA"}, "truth": truth})
    for fake in FAKE_NAMES:
        close = difflib.get_close_matches(norm(fake), list(all_norms), n=1, cutoff=0.7)
        assert norm(fake) not in all_norms and not close, f"{fake} is too close to a real product: {close}"
        code = rng.choice(sorted(eu.crops))
        cases.append({"stratum": "fake", "question": {"trade_name": fake, "crop": eu.crops[code], "country": "MA"},
                      "truth": {"status": "not_found", "crop_code": code, "note": "Invented name, absent from the ONSSA index (no close match at 0.7)"}})

    dev, heldout = [], []
    for stratum in TARGETS:
        group = [c for c in cases if c["stratum"] == stratum]
        rng.shuffle(group)
        k = round(len(group) * HELDOUT_SHARE)
        heldout += group[:k]
        dev += group[k:]
    for split, rows in (("dev", dev), ("heldout", heldout)):
        rows.sort(key=lambda c: (list(TARGETS).index(c["stratum"]), c["question"]["trade_name"].upper(), c["truth"]["crop_code"]))
        for i, c in enumerate(rows):
            c["id"], c["split"] = f"g2-{split}-{i + 1:03d}", split
    for path, rows in ((OUT_DEV, dev), (OUT_HELDOUT, heldout)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps({"id": c["id"], "split": c["split"], "stratum": c["stratum"],
                                            "question": c["question"], "truth": c["truth"]}, ensure_ascii=False) + "\n"
                                for c in rows), encoding="utf-8", newline="\n")

    exact_cases = [c for c in cases if c["stratum"] == "exact"]
    manifest = {
        "source": URL, "list_file": LIST_FILE.name, "snapshot": SNAPSHOT, "seed": SEED, "heldout_share": HELDOUT_SHARE,
        "total": len(cases), "dev": len(dev), "heldout": len(heldout),
        "strata": {s: {"target": n, "dev": sum(c["stratum"] == s for c in dev), "heldout": sum(c["stratum"] == s for c in heldout)}
                   for s, n in TARGETS.items()},
        "products_fetched_this_run": fetched, "products_qualified": len(qualified),
        "exact_registration_status": {s: sum(c["truth"]["registration_status"] == s for c in exact_cases)
                                      for s in sorted({c["truth"]["registration_status"] for c in exact_cases})},
        "substances_distinct": len({s["name_fr"] for c in cases for s in c["truth"].get("substances", [])}),
        "substances_not_resolved_by_rules_v0": sorted({s["name_fr"] for c in cases for s in c["truth"].get("substances", [])
                                                        if eu.substance(s["name_fr"]) is None}),
        "variant_kinds": sorted(c["truth"]["variant_kind"] for c in cases if c["stratum"] == "variant"),
        "variants_resolvable_by_exact_normalised_match": sum(c["truth"].get("resolvable_by_exact_normalised_match", False) for c in cases),
        "distinct_crops": len({c["truth"]["crop_code"] for c in cases}),
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
