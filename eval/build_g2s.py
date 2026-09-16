"""Build eval set G2s (substance-name resolution) from the seed and later label batches.

  eval/gold/g2s_seed.json        12 names, all dev (inspected while building S2)
  eval/labels/g2s_batch2.json    21 names; 10 go to held-out (fixed seed), 11 to dev

Writes eval/gold/g2s_dev.jsonl, eval/heldout/g2s_heldout.jsonl, eval/gold/g2s_manifest.json.
Every EU name in the labels must exist in the snapshot (checked here).

Usage: python eval/build_g2s.py
"""
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.eu_data import Snapshot  # noqa: E402

SEED = 20260917
HELDOUT_FROM_BATCH2 = 10
OUT_DEV = ROOT / "eval" / "gold" / "g2s_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g2s_heldout.jsonl"
OUT_MANIFEST = ROOT / "eval" / "gold" / "g2s_manifest.json"


def stratum(c):
    if c.get("expected") == "no_eu_substance":
        return "no_eu_substance"
    if c.get("family"):
        return "family"
    return "group_residue" if c.get("accept_same_residue") else "single"


def main():
    eu = Snapshot("2026-09-13")
    seed = json.loads((ROOT / "eval" / "gold" / "g2s_seed.json").read_text(encoding="utf-8"))["cases"]
    batch2 = json.loads((ROOT / "eval" / "labels" / "g2s_batch2.json").read_text(encoding="utf-8"))["cases"]
    for c in seed + batch2:
        name = c.get("eu_substance")
        if name and not c.get("family"):
            rec = eu.substance(name)
            assert rec and rec["substance_name"] == name, f"label {name!r} is not an exact EU name"
    names = [c["label_name"] for c in seed + batch2]
    assert len(names) == len(set(names)), "duplicate label names"

    rng = random.Random(SEED)
    order = list(range(len(batch2)))
    rng.shuffle(order)
    held = set(order[:HELDOUT_FROM_BATCH2])
    dev = [dict(c, batch="seed") for c in seed] + [dict(c, batch="batch2") for i, c in enumerate(batch2) if i not in held]
    heldout = [dict(c, batch="batch2") for i, c in enumerate(batch2) if i in held]

    for split, rows, path in (("dev", dev, OUT_DEV), ("heldout", heldout, OUT_HELDOUT)):
        lines = []
        for i, c in enumerate(rows):
            lines.append(json.dumps({"id": f"g2s-{split}-{i + 1:03d}", "split": split, "stratum": stratum(c),
                                     "question": {"label_name": c["label_name"]}, "truth": c}, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    manifest = {"seed": SEED, "total": len(dev) + len(heldout), "dev": len(dev), "heldout": len(heldout),
                "strata": {s: {"dev": sum(stratum(c) == s for c in dev), "heldout": sum(stratum(c) == s for c in heldout)}
                           for s in ("single", "group_residue", "family", "no_eu_substance")},
                "sources": {"seed": "eval/gold/g2s_seed.json", "batch2": "eval/labels/g2s_batch2.json"}}
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
