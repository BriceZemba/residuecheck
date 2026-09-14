"""Run one system on one eval set and score it.

Usage:
  python eval/run.py --suite g1 --config rules-only              # dev split (default)
  python eval/run.py --suite g2 --config rules-only --split heldout
  python eval/run.py --summary                                   # rebuild eval/results/README.md from all runs

Writes eval/results/<suite>_<config>_<split>.json (every answer and score) and .md (metrics, failures).
Held-out runs are appended to eval/results/heldout_runs.log, so how often the held-out set was used is on record.
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from residuecheck.onssa import norm  # noqa: E402
from systems import SYSTEMS, MissingKey  # noqa: E402

RESULTS = ROOT / "eval" / "results"
FILES = {("g1", "dev"): "gold/g1_dev.jsonl", ("g1", "heldout"): "heldout/g1_heldout.jsonl",
         ("g2", "dev"): "gold/g2_dev.jsonl", ("g2", "heldout"): "heldout/g2_heldout.jsonl"}


def load(suite, split):
    splits = ["dev", "heldout"] if split == "all" else [split]
    rows = []
    for s in splits:
        path = ROOT / "eval" / FILES[(suite, s)]
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


# Scoring

def score_g1(case, a):
    t = case["truth"]
    s = {"verdict_ok": a["verdict"] == t["verdict"],
         "false_green": a["verdict"] == "GREEN" and t["verdict"] != "GREEN",
         "missed_red": t["verdict"] == "RED" and a["verdict"] != "RED"}
    if t.get("eu_substance") is None:
        s["abstain_ok"] = a["verdict"] == "CANNOT_VERIFY"
    else:
        s["substance_ok"] = a.get("eu_substance") == t["eu_substance"]
        s["crop_ok"] = a.get("crop_code") == t["crop_code"]
        s["mrl_ok"] = (a.get("no_mrl_required") is True) if t["no_mrl_required"] else \
            (a.get("mrl_mg_per_kg") == t["mrl_mg_per_kg"] and a.get("at_loq") == t["at_loq"])
        s["over_abstain"] = a["verdict"] == "CANNOT_VERIFY"
    s["pass"] = s["verdict_ok"] and s.get("mrl_ok", True)
    return s


def score_g2(case, a):
    t = case["truth"]
    if t["status"] == "not_found":
        s = {"false_accept": a["status"] == "found"}
        s["pass"] = not s["false_accept"]
        return s
    found = a["status"] == "found"
    s = {"product_ok": found and norm(a.get("trade_name")) == norm(t["onssa_trade_name"]),
         "wrong_product": found and norm(a.get("trade_name")) != norm(t["onssa_trade_name"]),
         "abstained": not found}
    if s["product_ok"]:
        s["substances_ok"] = sorted(norm(x) for x in a.get("substances_fr", [])) == sorted(norm(x["name_fr"]) for x in t["substances"])
        s["registration_ok"] = a.get("registered_for_crop") == t["registered_for_crop"]
        s["dar_ok"] = a.get("dar_days") == t["dar_days"]
    s["pass"] = s["product_ok"] and s.get("substances_ok", False) and s.get("registration_ok", False) and s.get("dar_ok", False)
    return s


def rate(rows, key, where=lambda r: True):
    pool = [r for r in rows if where(r) and key in r["score"]]
    hits = sum(bool(r["score"][key]) for r in pool)
    return {"n": len(pool), "hits": hits, "rate": round(hits / len(pool), 3) if pool else None}


def metrics_g1(rows):
    m = {"pass": rate(rows, "pass"), "verdict_accuracy": rate(rows, "verdict_ok"),
         "mrl_accuracy": rate(rows, "mrl_ok"), "substance_resolved": rate(rows, "substance_ok"),
         "crop_resolved": rate(rows, "crop_ok"), "abstain_on_unknown": rate(rows, "abstain_ok"),
         "red_recall": rate(rows, "verdict_ok", lambda r: r["truth"]["verdict"] == "RED"),
         "false_green": sum(r["score"]["false_green"] for r in rows),
         "over_abstain": sum(r["score"].get("over_abstain", False) for r in rows)}
    m["by_stratum"] = {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in sorted({r["stratum"] for r in rows})}
    return m


def metrics_g2(rows):
    real = lambda r: r["stratum"] != "fake"  # noqa: E731
    m = {"pass": rate(rows, "pass"), "product_identified": rate(rows, "product_ok", real),
         "wrong_product": sum(r["score"].get("wrong_product", False) for r in rows),
         "abstained_on_real": sum(r["score"].get("abstained", False) for r in rows),
         "substances_exact": rate(rows, "substances_ok"), "registration_accuracy": rate(rows, "registration_ok"),
         "dar_accuracy": rate(rows, "dar_ok"), "fake_accepted": sum(r["score"].get("false_accept", False) for r in rows)}
    m["by_stratum"] = {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in sorted({r["stratum"] for r in rows})}
    return m


# Reporting

def git_version():
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "residuecheck", "eval/systems.py"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


def fmt_rate(r):
    return "n/a" if r["rate"] is None else f"{r['hits']}/{r['n']} ({r['rate']:.0%})"


def write_report(run):
    base = RESULTS / f"{run['suite']}_{run['config']}_{run['split']}"
    base.with_suffix(".json").write_text(json.dumps(run, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    m = run["metrics"]
    lines = [f"# {run['suite'].upper()} / {run['config']} / {run['split']}", "",
             f"{run['description']}", "",
             f"Run {run['run_at']}, code {run['code_version']}, {len(run['cases'])} cases, "
             f"{run['seconds']:.1f} s, cost ${run['cost_usd']:.4f}.", "", "| Metric | Value |", "|---|---|"]
    for k, v in m.items():
        if k == "by_stratum":
            continue
        lines.append(f"| {k} | {fmt_rate(v) if isinstance(v, dict) else v} |")
    lines += ["", "| Stratum | Pass |", "|---|---|"] + [f"| {s} | {fmt_rate(v)} |" for s, v in m["by_stratum"].items()]
    failures = [c for c in run["cases"] if not c["score"]["pass"]]
    lines += ["", f"## Failures ({len(failures)})", ""]
    if not failures:
        lines.append("None.")
    for c in failures:
        q, t, a = c["question"], c["truth"], c["answer"]
        bad_flags = ("false_green", "missed_red", "wrong_product", "false_accept", "over_abstain", "abstained")
        failed = ", ".join([k for k, v in c["score"].items() if k.endswith("_ok") and v is False] +
                           [k for k, v in c["score"].items() if k in bad_flags and v])
        if run["suite"] == "g1":
            lines.append(f"- `{c['id']}` [{c['stratum']}] {q['substance']!r} on {q['crop']!r} ({q['date']}): expected "
                         f"{t['verdict']} {t.get('mrl_mg_per_kg')}{'*' if t.get('at_loq') else ''} ({t.get('eu_substance')}), got "
                         f"{a['verdict']} {a.get('mrl_mg_per_kg')}{'*' if a.get('at_loq') else ''} ({a.get('eu_substance')}); failed: {failed}")
        else:
            lines.append(f"- `{c['id']}` [{c['stratum']}] {q['trade_name']!r} on {q['crop']!r}: expected {t['status']} "
                         f"{t.get('onssa_trade_name') or ''} registered={t.get('registered_for_crop')} DAR={t.get('dar_days')}, got "
                         f"{a['status']} {a.get('trade_name') or ''} registered={a.get('registered_for_crop')} DAR={a.get('dar_days')}; "
                         f"failed: {failed}")
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return base


def summary():
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS.glob("*.json"))]
    lines = ["# Eval results", "", "Generated by `python eval/run.py --summary`. Headline numbers come from held-out runs only.", ""]
    for suite, keys in (("g1", ["pass", "verdict_accuracy", "mrl_accuracy", "substance_resolved", "false_green", "over_abstain"]),
                        ("g2", ["pass", "product_identified", "wrong_product", "abstained_on_real", "registration_accuracy", "dar_accuracy", "fake_accepted"])):
        rows = [r for r in runs if r["suite"] == suite]
        if not rows:
            continue
        lines += [f"## {suite.upper()}", "", "| Config | Split | Code | " + " | ".join(keys) + " |", "|---" * (len(keys) + 3) + "|"]
        for r in rows:
            vals = [fmt_rate(r["metrics"][k]) if isinstance(r["metrics"][k], dict) else str(r["metrics"][k]) for k in keys]
            lines.append(f"| {r['config']} | {r['split']} | {r['code_version']} | " + " | ".join(vals) + " |")
        lines.append("")
    (RESULTS / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["g1", "g2"])
    ap.add_argument("--config", choices=sorted(SYSTEMS))
    ap.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if a.summary:
        return summary()
    if not (a.suite and a.config):
        ap.error("--suite and --config are required unless --summary")
    try:
        system = SYSTEMS[a.config]()
    except (MissingKey, NotImplementedError) as e:
        print(f"skipped: {e}")
        return 2
    if a.split != "dev":
        with (RESULTS / "heldout_runs.log").open("a", encoding="utf-8", newline="\n") as log:
            log.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{a.suite}\t{a.config}\t{a.split}\t{git_version()}\n")

    answer, scorer, metrics = (system.answer_g1, score_g1, metrics_g1) if a.suite == "g1" else (system.answer_g2, score_g2, metrics_g2)
    t0, cases = time.time(), []
    for case in load(a.suite, a.split):
        t = time.time()
        ans = answer(case["question"])
        cases.append({**case, "answer": ans, "score": scorer(case, ans), "latency_s": round(time.time() - t, 3)})
    run = {"suite": a.suite, "config": a.config, "split": a.split, "description": system.description,
           "run_at": datetime.datetime.now().isoformat(timespec="seconds"), "code_version": git_version(),
           "seconds": time.time() - t0, "cost_usd": sum(c["answer"].get("cost_usd") or 0 for c in cases),
           "metrics": metrics(cases), "cases": cases}
    base = write_report(run)
    print(base.with_suffix(".md").read_text(encoding="utf-8").split("## Failures")[0])
    summary()


if __name__ == "__main__":
    sys.exit(main())
