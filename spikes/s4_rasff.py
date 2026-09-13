"""Spike S4: export real RASFF pesticide-residue notifications for fruits and vegetables.

Source: DG SANTE open data API "API - iRASFF" (no subscription key needed at time of writing):
  https://api.datalake.sante.service.ec.europa.eu/rasff/irasff-general-info-view?format=json&api-version=v1.1
Found via RASFF Window's public configuration (openPortalLink). Paginated with `nextLink`.

The NOTIF_DATE_FROM filter returns HTTP 400 ("Edm.DateTimeOffset and Edm.String") for every date
format tried, so dates are filtered client-side.

Output: data/rasff_pesticides_fv.csv (committed) + spikes/results/s4-rasff.md.
The hazard field has the form "<substance> - {pesticide residues}", which gives the substance directly.

Usage: python spikes/s4_rasff.py [--origins Morocco Egypt Turkey ...] [--since 2024-01-01]
"""
import argparse
import collections
import csv
import pathlib
import re
import time

import requests

API = "https://api.datalake.sante.service.ec.europa.eu/rasff/irasff-general-info-view"
ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT.parent / "data"
OUT = ROOT / "results"
FIELDS = ["NOTIFICATION_REFERENCE", "NOTIF_DATE", "ORIGIN_COUNTRY_DESC", "NOTIFYNG_COUNTRY_DESC", "PRODUCT_NAME",
          "PRODUCT_CATEGORY_DESC", "HAZARD_CATEGORY_NAME", "substance", "unauthorised_flag", "NOTIFICATION_CLASSIFICAT_DESC",
          "NOTIFICATION_BASIS_DESC", "RISK_DECISION_DESC", "DISTRIBUTION_STATUS_DESC", "NOTIF_SUBJECT"]


def fetch_origin(session, origin, max_pages=200):
    url = API
    params = {"format": "json", "api-version": "v1.1", "ORIGIN_COUNTRY_DESC": origin}
    rows, pages = [], 0
    while url and pages < max_pages:
        r = session.get(url, params=params, timeout=120)
        r.raise_for_status()
        body = r.json()
        batch = body.get("value", [])
        rows += batch
        pages += 1
        url, params = body.get("nextLink"), None  # nextLink already carries the query
        time.sleep(0.3)
    return rows, pages


def hazards(rec):
    # Several hazards are joined in one field; keep the pesticide ones.
    parts = re.split(r"\s*\*\*\*\s*", rec.get("HAZARD_CATEGORY_NAME") or "")
    out = []
    for p in parts:
        if "{pesticide residues}" in p:
            raw = p.split(" - {")[0].strip()
            unauthorised = bool(re.search(r"unauthori[sz]ed", raw, re.I))
            name = re.sub(r"\s+unauthori[sz]ed(\s+substance)?\s*$", "", raw, flags=re.I).strip()
            out.append((name, unauthorised))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origins", nargs="+", default=["Morocco", "Egypt", "Türkiye", "Kenya", "India"])
    ap.add_argument("--since", default="2024-01-01")
    a = ap.parse_args()

    s = requests.Session()
    s.headers["User-Agent"] = "residuecheck/0.1 (hackathon research)"
    DATA.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    selected, stats = [], []
    for origin in a.origins:
        rows, pages = fetch_origin(s, origin)
        pest = []
        for rec in rows:
            date = (rec.get("NOTIF_DATE") or "")[:10]
            subs = hazards(rec)
            if date >= a.since and subs and rec.get("PRODUCT_CATEGORY_DESC") == "fruits and vegetables":
                for sub, unauthorised in subs:
                    pest.append({**{k: rec.get(k) for k in FIELDS}, "substance": sub, "unauthorised_flag": unauthorised,
                                 "NOTIF_DATE": date})
        dates = sorted((r.get("NOTIF_DATE") or "")[:10] for r in rows if r.get("NOTIF_DATE"))
        stats.append((origin, len(rows), pages, dates[0] if dates else "-", dates[-1] if dates else "-", len(pest)))
        selected += pest

    csv_path = DATA / "rasff_pesticides_fv.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(selected, key=lambda r: r["NOTIF_DATE"], reverse=True))

    by_sub = collections.Counter(r["substance"].lower() for r in selected)
    by_basis = collections.Counter(r["NOTIFICATION_BASIS_DESC"] for r in selected)
    refs = {r["NOTIFICATION_REFERENCE"] for r in selected}
    lines = ["# Spike S4 results: RASFF pesticide notifications (fruits and vegetables)", "",
             f"Run: {time.strftime('%Y-%m-%d %H:%M')}. Source: iRASFF open data API v1.1. Since {a.since}. "
             f"Time: {time.time() - t0:.0f} s.", "",
             "| Origin | Notifications fetched (all hazards) | Pages | Oldest | Newest | Pesticide x F&V rows since cutoff |",
             "|---|---|---|---|---|---|"]
    lines += [f"| {o} | {n} | {p} | {lo} | {hi} | {k} |" for o, n, p, lo, hi, k in stats]
    lines += ["", f"Distinct notifications selected: {len(refs)}; substance rows: {len(selected)}. File: `data/rasff_pesticides_fv.csv`.", "",
              "Top substances:", ""] + [f"- {sname}: {c}" for sname, c in by_sub.most_common(15)]
    lines += ["", "Notification basis:", ""] + [f"- {b}: {c}" for b, c in by_basis.most_common()]
    lines += ["", "Examples:", ""] + [f"- {r['NOTIFICATION_REFERENCE']} ({r['NOTIF_DATE']}, {r['ORIGIN_COUNTRY_DESC']}): "
                                      f"{r['substance']} in {r['PRODUCT_NAME'][:60]} [{r['NOTIFICATION_BASIS_DESC']}]"
                                      for r in sorted(selected, key=lambda r: r["NOTIF_DATE"], reverse=True)[:8]]
    (OUT / "s4-rasff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
