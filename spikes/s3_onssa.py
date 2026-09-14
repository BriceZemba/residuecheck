"""Spike S3: resolve a Moroccan trade name to active substances, crops and pre-harvest interval (DAR)
from the official ONSSA index phytosanitaire (https://eservice.onssa.gov.ma/IndPesticide.aspx).

The site is an ASP.NET WebForms app: every navigation is a __doPostBack with the page's viewstate.
Flow per lookup: GET home -> postback "Nom commercial" (list of all trade names, ~540 KB)
-> postback the product link (detail page, ~3 MB because of viewstate).

Only the structured tables are trusted (identity rows, active substances table, usages table).
Free-text sections on detail pages can contain text from other products (seen on ABAMEC: the
classification section names "CONAN"), so they are ignored.

Unknown names are never auto-matched: the lookup returns close matches as suggestions and status
"not_found". That is the CANNOT VERIFY guard.

Usage: python spikes/s3_onssa.py "ABAMEC" "ACTARA 25 WG" ...
Writes spikes/results/s3-onssa.md and caches parsed products in data/onssa_cache/.
The scraper itself now lives in residuecheck/onssa.py.
"""
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from residuecheck.onssa import Onssa  # noqa: E402  (scraper moved into the package on 2026-09-14)

OUT = ROOT / "results"


def main(names):
    OUT.mkdir(exist_ok=True)
    o = Onssa()
    t0 = time.time()
    n = o.load_list()
    lines = ["# Spike S3 results: ONSSA index phytosanitaire", "",
             f"Run: {time.strftime('%Y-%m-%d %H:%M')}. Index 'Dernière MAJ': {o.index_updated}. Trade names listed: {n}. "
             f"List load: {time.time() - t0:.1f} s.", "",
             "| Query | Status | Substances | Usages (crop: DAR days) | Registration / valid until | Time s |", "|---|---|---|---|---|---|"]
    results = []
    for q in names:
        t = time.time()
        try:
            rec = o.lookup(q)
        except Exception as e:
            rec = {"query": q, "status": f"error: {str(e)[:80]}"}
        results.append(rec)
        subs = "; ".join(f"{s['name_fr']} {s['content']}" for s in rec.get("substances", [])) or "-"
        uses = "; ".join(f"{u['crop_fr']}: {u['dar_days']}" for u in rec.get("usages", [])[:6]) or "-"
        if len(rec.get("usages", [])) > 6:
            uses += f" (+{len(rec['usages']) - 6} more)"
        reg = f"{rec.get('registration_no', '-')} / {rec.get('valid_until', '-')}"
        if rec["status"] == "not_found":
            subs, uses, reg = "-", f"suggestions: {', '.join(rec['suggestions']) or 'none'}", "-"
        lines.append(f"| {q} | {rec['status']} | {subs} | {uses} | {reg} | {time.time() - t:.1f} |")
    lines += ["", f"HTTP requests: {o.requests}. Total time: {time.time() - t0:.1f} s.", ""]
    (OUT / "s3-onssa.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return results


if __name__ == "__main__":
    main(sys.argv[1:] or ["ABAMEC", "ACTARA 25 WG"])
