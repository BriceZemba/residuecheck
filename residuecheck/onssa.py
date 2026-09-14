"""Read the official ONSSA index phytosanitaire (Morocco): trade name -> active substances, crops,
pre-harvest interval (DAR).

The site (https://eservice.onssa.gov.ma/IndPesticide.aspx) is an ASP.NET WebForms app: every navigation
is a __doPostBack carrying the page viewstate. Lookup flow: GET home -> postback "Nom commercial" (list of
all trade names, ~540 KB) -> postback the product link (detail page, ~3 MB).

Only structured tables are trusted (identity rows, active substances, usages). Free-text sections can
contain text from other products (seen on ABAMEC, whose classification section names "CONAN").

Unknown names are never auto-matched: the lookup returns close matches as suggestions with status
"not_found". Parsed products are cached in data/onssa_cache/, so eval runs work offline.
"""
import difflib
import json
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

URL = "https://eservice.onssa.gov.ma/IndPesticide.aspx"
DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
CACHE = DATA / "onssa_cache"
DELAY_S = 1.5  # be polite to a public government service


def norm(name):
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


class Onssa:
    def __init__(self, list_file=None):
        """list_file: a saved product list (see save_list) for offline name lookups; details still come from cache."""
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "residuecheck/0.1 (hackathon research; contact via github.com/BriceZemba)"
        self.list_html = None
        self.products = None  # {normalised name: (display name, postback target or None)}
        self.index_updated = None
        self.requests = 0
        if list_file:
            saved = json.loads(pathlib.Path(list_file).read_text(encoding="utf-8"))
            self.products = {norm(n): (n, None) for n in saved["products"]}
            self.index_updated = saved.get("index_updated")

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
        update = re.search(r"Dernière MAJ\s*:\s*([0-9/]+ [0-9:]+)", soup.get_text(" "))
        self.index_updated = update.group(1) if update else None
        return len(self.products)

    def save_list(self, path, retrieved):
        payload = {"source": URL, "retrieved": retrieved, "index_updated": self.index_updated,
                   "products": sorted(n for n, _ in self.products.values())}
        pathlib.Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    def names(self):
        return [n for n, _ in self.products.values()]

    def lookup(self, trade_name, offline=False):
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
        if offline:
            return {"query": trade_name, "status": "not_cached", "trade_name": name}
        if target is None or self.list_html is None:
            self.load_list()
            name, target = self.products[key]
        detail = self._postback(self.list_html, target)
        rec = parse_detail(detail)
        rec.update({"query": trade_name, "status": "found" if rec.get("substances") else "parse_failed",
                    "source": URL, "index_updated": self.index_updated, "retrieved": time.strftime("%Y-%m-%d")})
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        return rec


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
