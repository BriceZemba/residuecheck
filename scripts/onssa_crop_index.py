"""Index the ONSSA products registered for given crop names, and cache each product page.

The alternatives step needs "which products are registered for this crop", which the ONSSA site only offers as a
per-crop list (Recherche par Culture). Kept deliberately narrow: run it for the crops the demo and G6 need.

Output: data/onssa_crops_index.json  {crop_fr: {"retrieved": date, "products": [names]}}; details in data/onssa_cache/.

Usage: python scripts/onssa_crop_index.py "Agrumes" "Agrumes: Clémentinier" "Agrumes: Oranger"
"""
import datetime
import json
import pathlib
import re
import sys

from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.onssa import CACHE, URL, Onssa, norm  # noqa: E402

INDEX = ROOT / "data" / "onssa_crops_index.json"


def crop_lists(onssa, crops):
    onssa.requests += 1
    home = onssa.s.get(URL, timeout=60)
    page = onssa._postback(home.text, "ctl00$CPHCorps$lnkRech4")
    soup = BeautifulSoup(page, "html.parser")
    targets = {a.get_text(strip=True): re.search(r"__doPostBack\('([^']+)'", a["href"]).group(1)
               for a in soup.select("a[href][id^=ctl00_CPHCorps_lnkFiltre]")}
    out = {}
    for crop in crops:
        if crop not in targets:
            raise SystemExit(f"unknown ONSSA crop name: {crop!r}")
        listing = BeautifulSoup(onssa._postback(page, targets[crop]), "html.parser")
        out[crop] = sorted({a.get_text(strip=True) for a in listing.select("a[href][id^=ctl00_CPHCorps_lnkProduits]")})
    return out


def main(crops):
    onssa = Onssa()
    lists = crop_lists(onssa, crops)
    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    today = datetime.date.today().isoformat()
    for crop, names in lists.items():
        index[crop] = {"retrieved": today, "products": names}
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    todo = sorted({n for names in lists.values() for n in names if not (CACHE / f"{norm(n)}.json").exists()})
    print(f"{sum(len(v) for v in lists.values())} listed, {len(todo)} product pages to fetch", flush=True)
    onssa.load_list()
    failed = []
    for i, name in enumerate(todo, 1):
        try:
            rec = onssa.lookup(name)
            if rec.get("status") != "found":
                failed.append((name, rec.get("status")))
        except Exception as e:  # keep going; report at the end
            failed.append((name, str(e)[:80]))
        if i % 25 == 0:
            print(f"{i}/{len(todo)}", flush=True)
    print(f"done; {len(failed)} not parsed: {failed[:10]}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
