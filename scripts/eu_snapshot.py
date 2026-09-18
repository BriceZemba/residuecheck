"""Freeze a dated snapshot of the EU Pesticides Database for the crops ResidueCheck supports.

Sources (DG SANTE open data API v3.0, no key):
  active-substances-download        all active substances, NDJSON (~10 MB)
  pesticide-residues-mrls-download  every MRL version for every residue x product, NDJSON (~370 MB)
  pesticide-residues                residue definition names in EN and FR (FR is needed to match ONSSA names)

Raw downloads go to data/raw/ (git-ignored). The committed snapshot in data/eu_snapshot/<date>/ holds:
  manifest.json          date, source URLs, raw file sha256, row counts, join coverage
  substances.json.gz     compact active-substance records, incl. linked residue names and ids
  mrls.jsonl.gz          deduplicated MRL versions for the selected crops (all applicability states)
  residue_names.json.gz  residue id -> {EN, FR} names, and "replaces" (id of the residue definition it superseded)
  crops.json             selected EU product codes and names
  products.json.gz       full product classification: code -> parent code, EN/FR names, synonyms

Usage: python scripts/eu_snapshot.py [--date 2026-09-13] [--reuse-raw]
"""
import argparse
import datetime
import gzip
import hashlib
import io
import json
import pathlib
import re
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.eu_data import norm_residue  # noqa: E402

API = "https://api.datalake.sante.service.ec.europa.eu/sante/pesticides"
RAW = ROOT / "data" / "raw"

# Export crops for the EU from the origins in scope (Morocco first; Türkiye, Egypt, India, Kenya for the RASFF back-test).
CROPS = [
    "0110010", "0110020", "0110030", "0110040", "0110050",  # citrus
    "0130010", "0140010", "0140020", "0140030",              # apples, apricots, cherries, peaches
    "0151010", "0152000", "0153030", "0154010",              # table grapes, strawberries, raspberries, blueberries
    "0161010", "0161020", "0161030", "0163010", "0163030", "0163050",  # dates, figs, table olives, avocados, mangoes, pomegranates
    "0211000", "0220020", "0231010", "0231020", "0231030", "0231040",  # potatoes, onions, tomatoes, peppers, aubergines, okra
    "0232010", "0232030", "0233010", "0233030",              # cucumbers, courgettes, melons, watermelons
    "0251020", "0260010", "0260030",                         # lettuces, beans with pods, peas with pods
]

SUBSTANCE_FIELDS = ["substance_id", "substance_name", "cas_number", "substance_status", "approval_date", "expiry_date",
                    "substance_category", "candidate_for_substitution", "low_risk_active_substance", "basic_substance",
                    "pesticide_residue_linked", "pest_res_linked_legislation_url", "pest_res_mrl_webpage"]
MRL_FIELDS = ["pesticide_residue_id", "pesticide_residue_name", "product_code", "product_name",
              "mrl_value_only", "mrl_lod", "application_date", "applicability_text", "regulation_number",
              "regulation_url", "footnote_text"]


def download(session, endpoint, params, dest, reuse):
    if reuse and dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with session.get(f"{API}/{endpoint}", params={**params, "api-version": "v3.0"}, stream=True, timeout=600) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def gz_text(path):
    """Gzip text writer with a fixed header timestamp, so rebuilding identical data gives identical bytes."""
    # GzipFile opens (and closes) the file itself when given a path; a passed-in fileobj would be left open.
    return io.TextIOWrapper(gzip.GzipFile(path, mode="wb", mtime=0), encoding="utf-8")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paged(session, endpoint, params):
    url, p = f"{API}/{endpoint}", {**params, "format": "json", "api-version": "v3.0"}
    while url:
        r = session.get(url, params=p, timeout=120)
        r.raise_for_status()
        body = r.json()
        yield from body.get("value", [])
        url, p = body.get("nextLink"), None
        time.sleep(0.2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--reuse-raw", action="store_true", help="skip downloading if raw files exist")
    a = ap.parse_args()

    out = ROOT / "data" / "eu_snapshot" / a.date
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "residuecheck/0.1 (hackathon research)"
    t0 = time.time()

    subs_raw = download(s, "active-substances-download", {"format": "json"}, RAW / "active-substances.ndjson", a.reuse_raw)
    mrls_raw = download(s, "pesticide-residues-mrls-download", {"format": "json", "language_code": "EN"},
                        RAW / "pesticide-residues-mrls-EN.ndjson", a.reuse_raw)
    print(f"downloads ready in {time.time() - t0:.0f} s")

    # The download repeats a substance once per linked residue definition (and sometimes identically).
    # Collapse to one record per substance_id with a list of linked residues.
    by_id, substance_rows = {}, 0
    with subs_raw.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            substance_rows += 1
            rec = json.loads(line)
            linked = (rec.get("pesticide_residue_linked") or "").strip()
            entry = by_id.setdefault(rec["substance_id"], {k: rec.get(k) for k in SUBSTANCE_FIELDS if k != "pesticide_residue_linked"}
                                     | {"pesticide_residues_linked": [], "pesticide_residue_ids": []})
            if linked and linked not in entry["pesticide_residues_linked"]:
                entry["pesticide_residues_linked"].append(linked)
            # The MRL web link carries the linked residue ids (pest_res_id_list=...): a sturdier join than names,
            # which change when the EU redefines a residue.
            ids = re.search(r"pest_res_id_list=([\d,]+)", rec.get("pest_res_mrl_webpage") or "")
            for rid in (int(x) for x in ids.group(1).split(",") if x) if ids else ():
                if rid not in entry["pesticide_residue_ids"]:
                    entry["pesticide_residue_ids"].append(rid)
    substances = list(by_id.values())

    crop_set, crops, seen, mrls, total_rows = set(CROPS), {}, set(), [], 0
    residue_names_in_mrls = set()
    with mrls_raw.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total_rows += 1
            rec = json.loads(line)
            residue_names_in_mrls.add(norm_residue(rec["pesticide_residue_name"]))
            if rec["product_code"] not in crop_set:
                continue
            row = {k: rec.get(k) for k in MRL_FIELDS}
            key = tuple(row.values())
            if key in seen:  # the download repeats identical rows
                continue
            seen.add(key)
            crops[row["product_code"]] = row["product_name"]
            mrls.append(row)

    names = {}
    for lg in ("EN", "FR"):
        for rec in paged(s, "pesticide-residues", {"pesticide_residue_lg": lg}):
            entry = names.setdefault(str(rec["pesticide_residue_id"]), {})
            entry[lg] = rec["pesticide_residue_name"]
            # Version lineage: a redefined residue points back to the id it replaced.
            if rec.get("original_pesticide_residue_id"):
                entry["replaces"] = int(rec["original_pesticide_residue_id"])

    # Product classification (Annex I of Reg. 396/2005) with parents, so a group registration can cover a crop.
    products_by_id = {}
    for lg in ("EN", "FR"):
        for rec in paged(s, "pesticide-residues-products", {"language": lg}):
            p = products_by_id.setdefault(rec["product_id"], {"code": rec["product_code"], "parent_id": rec["product_parent_id"],
                                                               "type": rec["product_type_id"]})
            p[lg] = rec["product_name"]
            if lg == "EN":
                p["synonyms"] = rec.get("product_synonym_names")
    products = {p["code"]: {"parent": products_by_id.get(p["parent_id"], {}).get("code"), "type": p["type"],
                            "EN": p.get("EN"), "FR": p.get("FR"), "synonyms": p.get("synonyms")}
                for p in products_by_id.values()}

    missing_crops = sorted(crop_set - set(crops))
    linked = [x for x in substances if x["pesticide_residues_linked"]]
    joined = [x for x in linked if any(norm_residue(n) in residue_names_in_mrls for n in x["pesticide_residues_linked"])]

    with gz_text(out / "substances.json.gz") as f:
        json.dump(substances, f, ensure_ascii=False)
    with gz_text(out / "mrls.jsonl.gz") as f:
        for row in sorted(mrls, key=lambda r: (r["product_code"], r["pesticide_residue_id"])):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with gz_text(out / "residue_names.json.gz") as f:
        json.dump(names, f, ensure_ascii=False)
    (out / "crops.json").write_text(json.dumps(crops, ensure_ascii=False, indent=1), encoding="utf-8")
    with gz_text(out / "products.json.gz") as f:
        json.dump(products, f, ensure_ascii=False)

    manifest = {
        "snapshot_date": a.date,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "active_substances": f"{API}/active-substances-download?format=json&api-version=v3.0",
            "mrls": f"{API}/pesticide-residues-mrls-download?format=json&language_code=EN&api-version=v3.0",
            "residue_names": f"{API}/pesticide-residues?pesticide_residue_lg=EN|FR&format=json&api-version=v3.0",
        },
        "raw_sha256": {"active_substances": sha256(subs_raw), "mrls": sha256(mrls_raw)},
        "counts": {
            "substance_rows_in_download": substance_rows,
            "substances": len(substances),
            "mrl_rows_in_download": total_rows,
            "mrl_rows_selected_dedup": len(mrls),
            "crops_selected": len(crops),
            "residue_names": len(names),
            "products": len(products),
        },
        "missing_crop_codes": missing_crops,
        "substance_to_residue_join": {"substances_with_linked_residue": len(linked), "joined_to_mrl_names": len(joined)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    # Coverage of the full join (ids + redefinitions + names), measured through the same code the app uses.
    from residuecheck.eu_data import Snapshot

    snap = Snapshot(a.date)
    manifest["substance_to_residue_join"]["linked_with_rows_for_selected_crops"] = sum(
        bool(snap.residue_ids(x)) for x in snap.substances)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
