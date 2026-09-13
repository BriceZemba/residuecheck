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
"""
import difflib
import json
import pathlib
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

URL = "https://eservice.onssa.gov.ma/IndPesticide.aspx"
ROOT = pathlib.Path(__file__).resolve().parent
CACHE = ROOT.parent / "data" / "onssa_cache"
OUT = ROOT / "results"
DELAY_S = 1.5  # be polite to a public government service


class Onssa:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "residuecheck/0.1 (hackathon research; contact via github.com/BriceZemba)"
        self.list_html = None
        self.products = None  # {normalised name: (display name, postback target)}
        self.requests = 0

    def _hidden(self, html):
        soup = BeautifulSoup(html, "html.parser")
        return {i["name"]: i.get("value", "") for i in soup.select("input[type=hidden]") if i.get("name")}

    def _postback(self, html, target):
        data = self._hidden(html)
        data.update({"__EVENTTARGET": target, "__EVENTARGUMENT": ""})
        time.sleep(DELAY_S)
        self.requests += 1
        r = self.s.post(URL, data=data, timeout=120)
        r.raise_for_status()
        return r.text

    def load_list(self):
        self.requests += 1
        home = self.s.get(URL, timeout=60)
        home.raise_for_status()
        self.list_html = self._postback(home.text, "ctl00$CPHCorps$lnkRech8")
        soup = BeautifulSoup(self.list_html, "html.parser")
        self.products = {}
        for a in soup.select("a[href][id^=ctl00_CPHCorps_lnkProduits]"):
            name = a.get_text(strip=True)
            target = re.search(r"__doPostBack\('([^']+)'", a["href"]).group(1)
            self.products[norm(name)] = (name, target)
        update = re.search(r"Dernière MAJ\s*:\s*([0-9/]+ [0-9:]+)", BeautifulSoup(self.list_html, "html.parser").get_text(" "))
        self.index_updated = update.group(1) if update else None
        return len(self.products)

    def lookup(self, trade_name):
        if self.products is None:
            self.load_list()
        key = norm(trade_name)
        if key not in self.products:
            close = difflib.get_close_matches(key, list(self.products), n=3, cutoff=0.75)
            return {"query": trade_name, "status": "not_found", "suggestions": [self.products[c][0] for c in close]}
        name, target = self.products[key]
        cache_file = CACHE / f"{key}.json"
        if cache_file.exists():
            rec = json.loads(cache_file.read_text(encoding="utf-8"))
            rec["from_cache"] = True
            return rec
        detail = self._postback(self.list_html, target)
        rec = parse_detail(detail)
        rec.update({"query": trade_name, "status": "found" if rec.get("substances") else "parse_failed",
                    "source": URL, "index_updated": self.index_updated, "retrieved": time.strftime("%Y-%m-%d")})
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    rec = {}
    labels = {"Nom commercial": "trade_name", "Détenteur": "holder", "Fournisseur": "supplier",
              "Numéro homologation": "registration_no", "Valable jusqu'au": "valid_until",
              "Tableau toxicologique": "tox_table", "Catégorie": "category", "Formulation": "formulation"}
    for label, key in labels.items():
        el = soup.find(string=re.compile(r"^\s*" + re.escape(label) + r"\s*:"))
        if el is not None:
            text = el.find_parent("td").get_text(" ", strip=True)
            rec[key] = text.split(":", 1)[1].strip() if ":" in text else None
    rec["substances"], rec["usages"] = [], []
    head = soup.find(string=re.compile(r"^\s*Matière Active\s*$"))
    if head is not None:
        for tr in head.find_parent("table").find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(cells) == 2 and cells[0]:
                rec["substances"].append({"name_fr": cells[0], "content": cells[1]})
    head = soup.find(string=re.compile(r"^\s*DAR \(j\)\s*$"))
    if head is not None:
        # Columns differ between products (some add stage, max applications, interval), so map by header.
        # "Usage" spans two cells: crop then pest.
        rename = {"Usage": ["crop_fr", "pest_fr"], "Dose": ["dose"], "Stade Ennemi": ["pest_stage"],
                  "Max. Appli.": ["max_applications"], "Intervalle": ["interval_days"],
                  "Mode Traitement": ["mode"], "DAR (j)": ["dar_days"]}
        rows = head.find_parent("table").find_all("tr")
        columns = []
        for th in rows[0].find_all(["td", "th"], recursive=False):
            label = th.get_text(" ", strip=True)
            span = int(th.get("colspan") or 1)
            names = rename.get(label, [label] * span)
            columns += names + [f"{label}_{i}" for i in range(len(names), span)]
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td", recursive=False)]
            if len(cells) != len(columns):
                continue
            use = dict(zip(columns, cells))
            dar = use.get("dar_days", "")
            use["dar_days"] = int(dar) if dar.isdigit() else (dar or None)
            rec["usages"].append(use)
    return rec


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
