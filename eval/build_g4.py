"""Build eval set G4 (back-test): real EU border rejections and alerts (RASFF) for fruit and vegetables.

Each case is one RASFF notification for pesticide residues whose product maps to one of the 32 supported crops.
The question gives what a grower's log would give once products are resolved: crop, active substances and the date
(the notification date is used as the EU arrival date). The system answers with a verdict and a level per substance.

Truth has two parts:
  - independent of this project: the lot was rejected or alerted in the EU, and RASFF flags some substances as
    "unauthorised" (not approved in the EU). The rules should block those (RED) on the notification date.
  - from the EU snapshot (same data the rules use, so circular): the limit in force on that date for each substance.
    A limit at the limit of quantification (or no listed limit, so the 0.01 mg/kg default) means any detectable
    residue fails, so the lot was preventable from the spray log alone. A limit above it means the rejection depended
    on dose and timing, which a log check cannot see. The snapshot keeps only recent limit versions; where its history
    starts after the notification date the case is stratum "unknown_history" and the rules should not claim a verdict.

G4 therefore measures coverage of real rejections by the rules (how many would have been blocked or warned before
shipping), not prediction of measured residues. Crop and substance names are hand labels (eval/labels/g4_labels.json).

Usage: python eval/build_g4.py
"""
import collections
import csv
import datetime
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.eu_data import Snapshot  # noqa: E402

SEED = 20260916
HELDOUT_SHARE = 0.3
RASFF = ROOT / "data" / "rasff_pesticides_fv.csv"
LABELS = ROOT / "eval" / "labels" / "g4_labels.json"
OUT_DEV = ROOT / "eval" / "gold" / "g4_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g4_heldout.jsonl"
OUT_MANIFEST = ROOT / "eval" / "gold" / "g4_manifest.json"
PREVENTABLE = {"at_loq", "not_listed"}  # any detectable residue fails: preventable from the spray log alone
STRATA = ("preventable", "dose_dependent", "unknown_history")


def notifications():
    notes = {}
    with RASFF.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            n = notes.setdefault(r["NOTIFICATION_REFERENCE"], {
                "reference": r["NOTIFICATION_REFERENCE"], "notified_on": r["NOTIF_DATE"],
                "origin": r["ORIGIN_COUNTRY_DESC"], "product": r["PRODUCT_NAME"].strip(),
                "classification": r["NOTIFICATION_CLASSIFICAT_DESC"], "basis": r["NOTIFICATION_BASIS_DESC"],
                "subject": r["NOTIF_SUBJECT"].strip(), "rows": []})
            n["rows"].append((r["substance"].strip(), r["unauthorised_flag"] == "True"))
    return notes


def limits(eu, sub, crop, day):
    out = []
    for rid in eu.residue_ids(sub):
        m = eu.mrl_on(rid, crop, day)
        known = eu.mrl_versions(rid, crop)
        out.append({"residue_id": rid, "value": m.value if m else None, "at_loq": m.at_loq if m else None,
                    "no_mrl_required": m.no_mrl_required if m else None, "regulation": m.regulation if m else None,
                    "history_from": known[0].applies_from.isoformat() if known else None})
    return out


def limit_status(lims, default_only):
    """What the EU limit on the notification date says, as far as the snapshot knows.

    not_listed: the EU database links the substance only to the default limit of 0.01 mg/kg (Reg. 396/2005
    Art. 18(1)(b)) and no residue of its own has rows.
    history_not_in_snapshot: limits exist for this crop but the snapshot's history starts after the notification date.
    A residue whose first version is later than the date (a successor definition) is ignored when another has a value.
    """
    if not lims:
        return "not_listed" if default_only else "no_limit_for_crop"
    current = [x for x in lims if x["value"] is not None or x["no_mrl_required"]]
    if not current:
        return "history_not_in_snapshot" if any(x["history_from"] for x in lims) else "no_limit_for_crop"
    if any(x["at_loq"] for x in current):
        return "at_loq"
    return "no_mrl_required" if all(x["no_mrl_required"] for x in current) else "above_loq"


def main():
    eu = Snapshot("2026-09-13")
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    by_name, by_ref, sub_labels = labels["by_name"], labels["by_reference"], labels["substances"]
    skipped = collections.Counter()
    skipped_substances = collections.Counter()
    cases = []
    notes = notifications()
    for ref, n in sorted(notes.items()):
        label = by_ref.get(ref) or by_name.get(n["product"])
        if label is None:
            raise SystemExit(f"no label for product {n['product']!r} ({ref}); add it to {LABELS.name}")
        if label.startswith("skip:"):
            skipped[label[5:]] += 1
            continue
        crop, day = label, datetime.date.fromisoformat(n["notified_on"])
        subs = {}
        for raw, unauthorised in n["rows"]:
            mapped = sub_labels.get(raw)
            if mapped and mapped.startswith("skip:"):
                skipped_substances[mapped[5:]] += 1
                continue
            rec = eu.substance(mapped or raw)
            if rec is None:
                skipped_substances["not in the EU database"] += 1
                continue
            name = rec["substance_name"]
            entry = subs.setdefault(name, {"eu_substance": name, "as_notified": raw, "rasff_unauthorised": False,
                                           "limits": limits(eu, rec, crop, day),
                                           "default_limit_only": eu.default_limit_only(rec)})
            entry["rasff_unauthorised"] |= unauthorised
        if not subs:
            skipped["no checkable substance"] += 1
            continue
        truth_subs = sorted(subs.values(), key=lambda s: s["eu_substance"])
        for s in truth_subs:
            s["limit_status"] = limit_status(s["limits"], s["default_limit_only"])
        statuses = {s["limit_status"] for s in truth_subs}
        preventable = bool(statuses & PREVENTABLE)
        stratum = ("preventable" if preventable else
                   "unknown_history" if statuses & {"history_not_in_snapshot", "no_limit_for_crop"} else "dose_dependent")
        cases.append({"question": {"reference": ref, "notified_on": n["notified_on"], "origin": n["origin"],
                                   "product_as_notified": n["product"], "crop_code": crop, "crop": eu.crops[crop],
                                   "substances": [s["eu_substance"] for s in truth_subs]},
                      "truth": {"rejected": True, "classification": n["classification"], "basis": n["basis"],
                                "substances": truth_subs, "preventable_from_log": preventable,
                                "unauthorised": [s["eu_substance"] for s in truth_subs if s["rasff_unauthorised"]]},
                      "stratum": stratum})

    rng = random.Random(SEED)
    order = list(range(len(cases)))
    rng.shuffle(order)
    held = set(order[:round(len(cases) * HELDOUT_SHARE)])
    dev = [c for i, c in enumerate(cases) if i not in held]
    heldout = [c for i, c in enumerate(cases) if i in held]
    for split, rows, path in (("dev", dev, OUT_DEV), ("heldout", heldout, OUT_HELDOUT)):
        rows.sort(key=lambda c: c["question"]["reference"])
        path.write_text("".join(json.dumps({"id": f"g4-{split}-{i + 1:03d}", "split": split, "stratum": c["stratum"],
                                            "question": c["question"], "truth": c["truth"]}, ensure_ascii=False) + "\n"
                                for i, c in enumerate(rows)), encoding="utf-8", newline="\n")
    all_subs = [s for c in cases for s in c["truth"]["substances"]]
    manifest = {"seed": SEED, "source": "data/rasff_pesticides_fv.csv", "notifications": len(notes),
                "total": len(cases), "dev": len(dev), "heldout": len(heldout),
                "skipped_notifications": dict(sorted(skipped.items())),
                "skipped_substance_rows": dict(sorted(skipped_substances.items())),
                "strata": {s: sum(c["stratum"] == s for c in cases) for s in STRATA},
                "substance_rows": len(all_subs),
                "limit_status": dict(sorted(collections.Counter(s["limit_status"] for s in all_subs).items())),
                "rasff_unauthorised": sum(s["rasff_unauthorised"] for s in all_subs),
                "unauthorised_but_limit_above_loq": sorted({s["eu_substance"] for s in all_subs
                                                            if s["rasff_unauthorised"] and s["limit_status"] == "above_loq"}),
                "crops": dict(sorted(collections.Counter(c["question"]["crop"] for c in cases).items(), key=lambda x: -x[1])),
                "origins": dict(sorted(collections.Counter(c["question"]["origin"] for c in cases).items(), key=lambda x: -x[1])),
                "labels": "eval/labels/g4_labels.json", "snapshot": "2026-09-13"}
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
