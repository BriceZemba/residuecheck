"""Parsers for two official pesticide registers, read by product page (S6, 2026-09-16).

Türkiye  BKÜ, Bitki Koruma Ürünleri Veri Tabanı   https://bku.tarimorman.gov.tr/BKURuhsat/Details/{id}
Egypt    APC, Agricultural Pesticide Committee     http://www.apc.gov.eg/ar/PesticideDetails.aspx?id={id}

Used to build eval set G2b with truth fetched directly from the register (not through Tavily), and cached in
data/registers_cache/. Both parsers return None for pages without a product.
"""
import datetime
import json
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

CACHE = pathlib.Path(__file__).resolve().parents[1] / "data" / "registers_cache"
URLS = {
    "TR": "https://bku.tarimorman.gov.tr/BKURuhsat/Details/{id}",
    "EG": "http://www.apc.gov.eg/ar/PesticideDetails.aspx?id={id}",
}
DELAY_S = 1.5
_CONC = re.compile(r"^[\s%]*[\d.,]+(\s*x\s*10\^?\d+)?\s*(%|g/l|g/kg|gr/l|mg/l|ml/l|cfu/\S+|spor/\S+|IU/\S+)?\s*", re.I)


def split_substances(text):
    """'%25,2 Boscalid + %12,8 Pyraclostrobin' -> ['Boscalid', 'Pyraclostrobin']."""
    out = []
    for part in re.split(r"\s\+\s|\+", text or ""):
        name = _CONC.sub("", part.strip()).strip(" ,;")
        if name:
            out.append(name)
    return out


def parse_bku(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h3")
    if title is None or soup.find(string=re.compile("Ruhsat Detay")) is None:
        return None
    rows = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) == 2 and cells[0] not in rows:
            rows[cells[0]] = cells[1]
    if "Aktif Madde" not in rows:
        return None
    heading = title.get_text(" ", strip=True)
    trade_name = re.sub(r"\s*\((İMAL|İTHAL|IMAL|ITHAL)\)\s*$", "", heading).strip()
    valid_until = rows.get("Geçerlilik Süresi")
    try:
        valid = datetime.datetime.strptime(valid_until, "%d.%m.%Y").date() if valid_until else None
    except ValueError:
        valid = None
    return {"trade_name": trade_name, "heading": heading, "active_substance_text": rows["Aktif Madde"],
            "substances": split_substances(rows["Aktif Madde"]), "formulation": rows.get("Formulasyonu"),
            "licence_no": rows.get("Ruhsat Numarası"), "licence_group": rows.get("Ruhsat Grubu"),
            "valid_until": valid.isoformat() if valid else valid_until, "holder": rows.get("Ruhsat Sahibi Firma")}


def parse_apc(html):
    soup = BeautifulSoup(html, "html.parser")
    name = soup.find(id="content_ContentPlaceHolder1_dvProduct_lblName")
    if name is None or not name.get_text(strip=True):
        return None
    subs = [a.get_text(" ", strip=True) for a in soup.select("[id^=content_ContentPlaceHolder1_dvProduct_DataList1_HyperLink1_]")]
    status = soup.find(id="content_ContentPlaceHolder1_dvProduct_hlStatus")
    rows = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) == 2 and cells[0] not in rows:
            rows[cells[0]] = cells[1]
    phis = [p.get_text(" ", strip=True) for p in soup.select("[id*=lblPHI_]")]
    return {"trade_name": name.get_text(" ", strip=True), "substances": [s for s in subs if s],
            "registration_no": rows.get("رقم التسجيل"), "concentration": rows.get("التركيز"),
            "status": status.get_text(strip=True) if status else None, "producer": rows.get("الشركة المنتجة"),
            "use_class": rows.get("تصنيفات الإستخدام"), "pre_harvest_intervals": phis}


PARSERS = {"TR": parse_bku, "EG": parse_apc}


def fetch(country, product_id, session=None, use_cache=True):
    """Fetch and parse one product page; cached as JSON (including 'no product' results)."""
    path = CACHE / country / f"{product_id}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    session = session or requests.Session()
    url = URLS[country].format(id=product_id)
    time.sleep(DELAY_S)
    r = session.get(url, timeout=60, headers={"User-Agent": "residuecheck/0.1 (hackathon research; github.com/BriceZemba)"})
    record = PARSERS[country](r.text) if r.status_code == 200 else None
    out = {"country": country, "id": product_id, "url": url, "http_status": r.status_code,
           "retrieved": datetime.date.today().isoformat(), "product": record}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return out
