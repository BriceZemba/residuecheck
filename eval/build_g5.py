"""Build eval set G5 (end to end): 8 hand-labelled spray logs checked through the whole API.

Truth is written by hand in eval/labels/g5_scenarios.json, with the reasoning and the facts it relies on. This builder
does not compute any truth: it only re-checks that each cited label fact (product registered on a crop with that
pre-harvest interval) still matches the ONSSA cache, then splits the cases (30% held out, fixed seed).

What G5 measures, beyond the verdict: the guards. No GREEN when the truth is not GREEN, no silent correction of a
product name, every blocking finding cites a source, planned and applied sprays framed correctly, and every safer
option shown actually passes the rules when substituted into the lot.

Usage: python eval/build_g5.py
"""
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.alternatives import _load_record  # noqa: E402

SEED = 20260918
HELDOUT_SHARE = 0.3
LABELS = ROOT / "eval" / "labels" / "g5_scenarios.json"
OUT_DEV = ROOT / "eval" / "gold" / "g5_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g5_heldout.jsonl"


def check_fact(product, crop_fr, dar):
    rec = _load_record(product)
    if rec is None:
        return f"{product}: not in the ONSSA cache"
    dars = {u["dar_days"] for u in rec["usages"] if u["crop_fr"] == crop_fr}
    if not dars:
        return f"{product}: no usage on {crop_fr}"
    if dar not in dars:
        return f"{product}: DAR on {crop_fr} is {sorted(dars)}, label says {dar}"
    return None


def main():
    scenarios = json.loads(LABELS.read_text(encoding="utf-8"))["scenarios"]
    problems = [p for s in scenarios for p in (check_fact(*f) for f in s["facts"]) if p]
    if problems:
        raise SystemExit("label facts no longer match the ONSSA cache:\n  " + "\n  ".join(problems))
    rng = random.Random(SEED)
    ids = sorted(s["id"] for s in scenarios)
    held = set(rng.sample(ids, round(len(ids) * HELDOUT_SHARE)))
    for split, path in (("dev", OUT_DEV), ("heldout", OUT_HELDOUT)):
        rows = []
        for s in scenarios:
            if (s["id"] in held) != (split == "heldout"):
                continue
            question = {"kind": "csv", **s["csv"]} if "csv" in s else {"kind": "rows", **s["request"]}
            rows.append({"id": s["id"], "split": split, "stratum": s["truth"]["verdict"], "title": s["title"],
                         "question": question, "truth": s["truth"], "why": s["why"]})
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(json.dumps({"total": len(scenarios), "heldout": sorted(held), "facts_checked": sum(len(s["facts"]) for s in scenarios)}))


if __name__ == "__main__":
    main()
