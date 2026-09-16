"""Build eval set G2b (trade-name resolution beyond Morocco): Türkiye (BKÜ) and Egypt (APC).

Truth is fetched directly from the official register product pages (residuecheck/registers.py), never through
Tavily, so the set does not depend on the search engine the system under test uses.

Strata:
  tr_exact  6  currently licensed Turkish products (validity date after the build date), name as on the register
  eg_exact  6  Egyptian products with status "مسجل" (registered), Arabic trade name as on the register
  fake      3  invented names (1 Latin, 2 Arabic); absence checked with a domain-restricted Tavily search

Technical-grade entries (Arabic "خام", TEKNİK, TECHNICAL, TC) are skipped: growers do not spray them.
Only products whose every active substance maps to an EU database name are kept, so the substance part of the
truth can be scored. Product IDs are drawn at random (fixed seed). 30% of each stratum is held out.

Usage: python eval/build_g2b.py   (network on first run; register pages are cached in data/registers_cache/)
"""
import datetime
import json
import pathlib
import random
import re
import shutil
import subprocess
import sys

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.eu_data import Snapshot  # noqa: E402
from residuecheck.registers import fetch  # noqa: E402
from residuecheck.resolver import squash  # noqa: E402

SEED = 20260916
BUILD_DATE = datetime.date(2026, 9, 16)
TARGETS = {"tr_exact": 6, "eg_exact": 6, "fake": 3}
ID_RANGES = {"TR": (1, 11400), "EG": (3000, 31000)}
MAX_FETCH = {"TR": 40, "EG": 300}
HELDOUT_SHARE = 0.3
FAKES = [("VERONEX 35 SC", "TR", "bku.tarimorman.gov.tr"),
         ("بلوفين 25% EC", "EG", "apc.gov.eg"),
         ("زيرولان 50% WP", "EG", "apc.gov.eg")]
OUT_DEV = ROOT / "eval" / "gold" / "g2b_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g2b_heldout.jsonl"
OUT_MANIFEST = ROOT / "eval" / "gold" / "g2b_manifest.json"


def usable(country, rec, eu):
    p = rec["product"]
    if not p or not p["substances"] or len(p["trade_name"]) < 3:
        return None
    # Technical-grade active ingredient ("خام" = raw; TEKNİK/TECHNICAL) is registered for import, not sprayed by growers.
    if re.search(r"خام|TEKN[İI]K|TECHNICAL|TC", p["trade_name"], re.I):
        return None
    if country == "TR" and not (re.match(r"\d{4}-\d{2}-\d{2}$", p.get("valid_until") or "")
                                and p["valid_until"] >= BUILD_DATE.isoformat()):
        return None
    if country == "EG" and p.get("status") != "مسجل":
        return None
    eu_names = []
    for s in p["substances"]:
        hit = eu.substance(s)
        if hit is None:
            return None
        eu_names.append(hit["substance_name"])
    return eu_names


def sample(country, n, eu, rng, session):
    lo, hi = ID_RANGES[country]
    ids = rng.sample(range(lo, hi + 1), MAX_FETCH[country])
    picked, fetched, names = [], 0, set()
    for pid in ids:
        if len(picked) >= n:
            break
        rec = fetch(country, pid, session=session)
        fetched += 1
        eu_names = usable(country, rec, eu)
        if eu_names is None or squash(rec["product"]["trade_name"]) in names:
            continue
        names.add(squash(rec["product"]["trade_name"]))
        picked.append((rec, eu_names))
    return picked, fetched


def absent_on_register(name, domain):
    """True if a domain-restricted Tavily search returns no page containing the name; None if Tavily is unavailable."""
    exe = shutil.which("tvly")
    if not exe:
        return None
    proc = subprocess.run([exe, "search", name, "--include-domains", domain, "--max-results", "10", "--json"],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        return None
    results = json.loads(proc.stdout).get("results", [])
    return not any(squash(name) in squash(f"{r.get('title', '')} {r.get('content', '')}") for r in results)


def main():
    eu = Snapshot("2026-09-13")
    rng = random.Random(SEED)
    session = requests.Session()
    cases, stats = [], {}
    for stratum, country in (("tr_exact", "TR"), ("eg_exact", "EG")):
        picked, fetched = sample(country, TARGETS[stratum], eu, rng, session)
        stats[stratum] = {"target": TARGETS[stratum], "found": len(picked), "pages_fetched": fetched}
        for rec, eu_names in picked:
            p = rec["product"]
            cases.append({"stratum": stratum, "question": {"trade_name": p["trade_name"], "country": country},
                          "truth": {"status": "found", "trade_name": p["trade_name"], "substances_page": p["substances"],
                                    "eu_substances": eu_names, "url": rec["url"], "register_id": rec["id"],
                                    "retrieved": rec["retrieved"],
                                    "details": {k: v for k, v in p.items() if k not in ("trade_name", "substances")}}})
    absence = {}
    for name, country, domain in FAKES:
        absence[name] = absent_on_register(name, domain)
        assert absence[name] is not False, f"{name} appears on {domain}"
        cases.append({"stratum": "fake", "question": {"trade_name": name, "country": country},
                      "truth": {"status": "not_found", "note": f"invented; domain-restricted Tavily search on {domain} "
                                f"found no page with this name ({BUILD_DATE})" if absence[name] else "invented; absence not checked"}})

    dev, heldout = [], []
    for stratum in TARGETS:
        group = [c for c in cases if c["stratum"] == stratum]
        rng.shuffle(group)
        k = round(len(group) * HELDOUT_SHARE)
        heldout += group[:k]
        dev += group[k:]
    for split, rows, path in (("dev", dev, OUT_DEV), ("heldout", heldout, OUT_HELDOUT)):
        rows.sort(key=lambda c: (list(TARGETS).index(c["stratum"]), c["question"]["trade_name"]))
        for i, c in enumerate(rows):
            c["id"], c["split"] = f"g2b-{split}-{i + 1:03d}", split
        path.write_text("".join(json.dumps({"id": c["id"], "split": c["split"], "stratum": c["stratum"],
                                            "question": c["question"], "truth": c["truth"]}, ensure_ascii=False) + "\n"
                                for c in rows), encoding="utf-8", newline="\n")
    manifest = {"seed": SEED, "build_date": BUILD_DATE.isoformat(), "snapshot": "2026-09-13", "total": len(cases),
                "dev": len(dev), "heldout": len(heldout), "strata": stats, "fakes_absence_checked": absence,
                "sources": {"TR": "https://bku.tarimorman.gov.tr/BKURuhsat/Details/{id}",
                            "EG": "http://www.apc.gov.eg/ar/PesticideDetails.aspx?id={id}"}}
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
