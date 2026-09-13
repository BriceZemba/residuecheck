"""Print rules-engine v0 results for a seeded spray log (invented applications, real regulatory data).

Registration and DAR for ACTARA 25 WG come from the cached ONSSA record (data/onssa_cache/ACTARA25WG.json,
usage "Agrumes"). The crop mapping Agrumes -> Oranges is done by hand here; automating it is later work.

Usage: python scripts/demo_rules.py > examples/seeded-orange-lot.md
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.eu_data import Snapshot  # noqa: E402
from residuecheck.rules import Application, Level, Lot, evaluate  # noqa: E402

actara = json.loads((ROOT / "data" / "onssa_cache" / "ACTARA25WG.json").read_text(encoding="utf-8"))
citrus_dar = next(u["dar_days"] for u in actara["usages"] if u["crop_fr"] == "Agrumes")

lot = Lot(
    crop_code="0110020",  # Oranges
    harvest_on="2026-10-01",
    applications=[
        Application(actara["trade_name"], "2026-08-15", [s["name_fr"] for s in actara["substances"]],
                    registered_for_crop=True, dar_days=citrus_dar, source=actara["source"]),
        Application("PYRIPROXYFEN 100 EC (seeded)", "2026-09-10", ["Pyriproxyfène"], registered_for_crop=True, dar_days=30),
        Application("SOUFRE 80 WG (seeded)", "2026-09-25", ["Soufre"], registered_for_crop=True, dar_days=3),
        Application("ZORBEX 300 SC (seeded, fake name)", "2026-08-01", [], registered_for_crop=None),
    ],
)
result = evaluate(lot, Snapshot())

print("# Seeded lot: oranges, harvest 2026-10-01\n")
print("Seeded spray records; regulatory data is real (EU snapshot 2026-09-13, ONSSA index retrieved 2026-09-13).\n")
print(f"**Verdict: {result.verdict.name}**" + (f" (earliest safe harvest: {result.earliest_safe_harvest})" if result.earliest_safe_harvest else ""))
print("\n| Level | Code | Product | Finding | Sources |\n|---|---|---|---|---|")
for f in sorted(result.findings, key=lambda f: -f.level):
    print(f"| {f.level.name} | {f.code} | {f.product or ''} | {f.message} | {' '.join(f.sources)} |")
print("\nAssumptions:\n")
for a in result.assumptions:
    print(f"- {a}")
