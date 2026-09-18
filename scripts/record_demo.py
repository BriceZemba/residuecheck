"""Record the live agents on the demo scenarios, so the hosted demo can replay them without keys.

Needs NEBIUS_API_KEY (Token Factory) and, for web search, TAVILY_API_KEY or a logged-in Tavily CLI.
Each scenario is run twice: the second run replays the fresh recording and must give the same answer, otherwise
the scenario is not marked as recorded (it would not replay faithfully).

Usage: python scripts/record_demo.py [--session demo-2026-10-05] [--only planned-spray]
Output: data/replays/<session>.json (commit it; it holds model replies and public search results, no keys).
"""
import argparse
import datetime
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck import api  # noqa: E402
from residuecheck.engine import Engine, from_env  # noqa: E402
from residuecheck.replay import ReplayModel, ReplaySearch, Store  # noqa: E402
from residuecheck.search import MissingKey  # noqa: E402


def comparable(body):
    """What a judge sees, without timing or cost fields."""
    return {"verdict": body["verdict"], "findings": [(f["code"], f["product"], f["substance"]) for f in body["findings"]],
            "applications": [(a["status"], a["trade_name"], a["suggestions"], a["resolution"].get("method"),
                              [o["product"] for o in (a.get("alternatives") or {}).get("options", [])])
                             for a in body["applications"]]}


def run(request):
    req = api.CheckRequest(**request)
    return api.run_check(req.crop_code, req.harvest_on, req.arrival_on, req.applications, req.today)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=f"demo-{datetime.date.today().isoformat()}")
    ap.add_argument("--only", action="append")
    a = ap.parse_args()
    try:
        live = from_env({**os.environ, "RESIDUECHECK_ENGINE": "live", "RESIDUECHECK_RECORD": a.session,
                         "RESIDUECHECK_DAILY_USD": "5"})
    except MissingKey as e:
        print(f"cannot record: {e}")
        return 2
    scenarios = json.loads((ROOT / "data" / "demo_scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    results = {}
    for s in scenarios:
        if a.only and s["id"] not in a.only:
            continue
        api.set_engine(live)
        body = run(s["request"])
        live.session.save()
        store = Store(live.session.folder)
        api.set_engine(Engine("replay", ReplayModel(store, live.model_name), ReplaySearch(store), store=store))
        again = run(s["request"])
        same = comparable(body) == comparable(again)
        fell_back = [x["resolution"].get("note") for x in again["applications"] if x["resolution"].get("note")]
        fell_back += [x["alternatives"]["fallback_note"] for x in again["applications"]
                      if x.get("alternatives") and x["alternatives"].get("fallback_note")]
        ok = same and not fell_back
        if ok:
            live.session.scenarios.append(s["id"])
        results[s["id"]] = {"verdict": body["verdict"], "replays": ok, "fallbacks": fell_back,
                            "agent_runs": sum(x["resolution"].get("method") == "agent" for x in body["applications"])
                            + sum((x.get("alternatives") or {}).get("method") == "agent" for x in body["applications"])}
        print(s["id"], json.dumps(results[s["id"]], ensure_ascii=False))
    path = live.session.save()
    print(f"saved {path} ({len(live.session.entries)} entries, scenarios {live.session.scenarios})")
    return 0 if all(r["replays"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
