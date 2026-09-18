"""Run one system on one eval set and score it.

Usage:
  python eval/run.py --suite g1 --config rules-only              # dev split (default)
  python eval/run.py --suite g2 --config rules-only --split heldout
  python eval/run.py --suite g2s --config rules-fuzzy            # substance names
  python eval/run.py --suite g2b --config full                   # Türkiye / Egypt trade names
  python eval/run.py --suite g3 --config full                    # spray-log photos (needs a vision model)
  python eval/run.py --suite g4 --config rules-only              # back-test on real RASFF notifications
  python eval/run.py --summary                                   # rebuild eval/results/README.md from all runs

Writes eval/results/<suite>_<config>_<split>.json (every answer and score) and .md (metrics, failures).
Held-out runs are appended to eval/results/heldout_runs.log, so how often the held-out set was used is on record.
"""
import argparse
import datetime
import difflib
import json
import pathlib
import re
import subprocess
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from residuecheck.onssa import norm  # noqa: E402
from systems import SYSTEMS, MissingKey  # noqa: E402

RESULTS = ROOT / "eval" / "results"
SUITES = ("g1", "g2", "g2b", "g2s", "g3", "g4", "g6")
FILES = {(s, "dev"): f"gold/{s}_dev.jsonl" for s in SUITES} | {(s, "heldout"): f"heldout/{s}_heldout.jsonl" for s in SUITES}


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
    if not found:
        # Asking the user with the right first suggestion is safe and useful, but not the same as resolving.
        s["first_suggestion_ok"] = bool(a.get("suggestions")) and norm(a["suggestions"][0]) == norm(t["onssa_trade_name"])
    if s["product_ok"]:
        s["substances_ok"] = sorted(norm(x) for x in a.get("substances_fr", [])) == sorted(norm(x["name_fr"]) for x in t["substances"])
        s["registration_ok"] = a.get("registered_for_crop") == t["registered_for_crop"]
        s["dar_ok"] = a.get("dar_days") == t["dar_days"]
    s["pass"] = s["product_ok"] and s.get("substances_ok", False) and s.get("registration_ok", False) and s.get("dar_ok", False)
    return s


def score_g2b(case, a):
    t = case["truth"]
    if t["status"] == "not_found":
        s = {"false_accept": a["status"] in ("found", "resolved")}
        s["pass"] = not s["false_accept"]
        return s
    from residuecheck.resolver import squash

    confirmed = a["status"] == "resolved"
    s = {"product_ok": confirmed and squash(a.get("trade_name")) == squash(t["trade_name"]),
         "wrong_product": confirmed and squash(a.get("trade_name")) != squash(t["trade_name"]),
         "abstained": not confirmed}
    if s["product_ok"]:
        s["substances_ok"] = sorted(a.get("eu_substances") or []) == sorted(t["eu_substances"])
    s["pass"] = s["product_ok"] and s.get("substances_ok", False)
    return s


def metrics_g2b(rows):
    real = lambda r: r["stratum"] != "fake"  # noqa: E731
    return {"pass": rate(rows, "pass"), "product_identified": rate(rows, "product_ok", real),
            "substances_exact": rate(rows, "substances_ok"),
            "wrong_product": sum(r["score"].get("wrong_product", False) for r in rows),
            "abstained_on_real": sum(r["score"].get("abstained", False) for r in rows),
            "fake_accepted": sum(r["score"].get("false_accept", False) for r in rows),
            "by_stratum": {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in sorted({r["stratum"] for r in rows})}}


def score_g6(case, a):
    t = case["truth"]
    safe, latest = set(t["safe_products"]), t["latest_spray"]

    def unsafe(option):
        name, when = option.get("product"), option.get("spray_on")
        if name not in safe:
            return True
        return bool(when) and when > latest[name]

    proposed = list(a.get("proposed") or [])
    shown_unsafe = [o["product"] for o in a["shown"] if unsafe(o)]
    proposed_unsafe = [o.get("product") for o in proposed if unsafe(o)]
    found = any(not unsafe(o) for o in a["shown"])
    ok = not shown_unsafe and (found if t["has_safe_option"] else not a["shown"])
    s = {"pass": ok, "shown_unsafe": len(shown_unsafe), "proposed": len(proposed),
         "proposed_unsafe": len(proposed_unsafe), "rejected": a.get("rejected", 0)}
    if t["has_safe_option"]:
        s["coverage_ok"] = found
    return s


def metrics_g6(rows):
    proposed = sum(r["score"]["proposed"] for r in rows)
    unsafe = sum(r["score"]["proposed_unsafe"] for r in rows)
    return {"pass": rate(rows, "pass"), "coverage": rate(rows, "coverage_ok"),
            "shown_unsafe": sum(r["score"]["shown_unsafe"] for r in rows),
            "unsafe_proposal_rate": {"n": proposed, "hits": unsafe, "rate": round(unsafe / proposed, 3) if proposed else None},
            "rejected_by_verifier": sum(r["score"]["rejected"] for r in rows),
            "by_stratum": {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in sorted({r["stratum"] for r in rows})}}


G3_FIELDS = ("date", "product", "dose", "target")


def _g3_norm(field, value):
    if value is None:
        return None
    v = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    if field in ("product", "dose"):
        v = re.sub(r"[\s\-_.]", "", v.replace(",", "."))
    return re.sub(r"\s+", " ", v).strip()


def _g3_field_ok(field, truth_row, value):
    got = _g3_norm(field, value)
    if got is None:
        return False
    if field == "product":
        return got in {_g3_norm(field, truth_row["product_as_written"]), _g3_norm(field, truth_row["product"])}
    if field == "target":
        return difflib.SequenceMatcher(None, got, _g3_norm(field, truth_row[field])).ratio() >= 0.9
    return got == _g3_norm(field, truth_row[field])


def _g3_similarity(t, p):
    score = weight = 0.0
    for field, w in (("product", 0.45), ("date", 0.3), ("dose", 0.15), ("target", 0.1)):
        tv = t["product_as_written"] if field == "product" else t[field]
        if tv is None or p.get(field) is None:
            continue
        weight += w
        score += w * difflib.SequenceMatcher(None, _g3_norm(field, tv), _g3_norm(field, p[field])).ratio()
    return score / weight if weight else 0.0


def score_g3(case, a):
    """Rows found, fields right, unreadable cells left empty, crossed-out lines not used, nothing invented."""
    truth, parsed = case["truth"]["rows"], a.get("rows") or []
    resolved = a.get("resolved")
    # Best-first matching over all pairs, so a crossed-out line cannot take the parse of its own correction.
    pairs = sorted(((_g3_similarity(t, p), -i, -j) for i, t in enumerate(truth) for j, p in enumerate(parsed)), reverse=True)
    match, used = {}, set()
    for sim, i, j in pairs:
        if sim >= 0.5 and -i not in match and -j not in used:
            match[-i] = -j
            used.add(-j)
    free = set(range(len(parsed))) - used
    s = {"rows_expected": 0, "rows_found": 0, "extra_rows": 0, "crossed_used": 0, "fields_checked": 0,
         "fields_ok": 0, "unreadable_expected": 0, "unreadable_empty": 0, "unreadable_flagged": 0,
         "guessed_unreadable": 0, "false_unreadable_flags": 0, "resolved_checked": 0, "resolved_ok": 0,
         "resolved_wrong": 0, "field_errors": []}
    for i, t in enumerate(truth):
        best = match.get(i)
        if t["crossed_out"]:
            if best is not None:
                if not parsed[best].get("crossed_out"):
                    s["crossed_used"] += 1
                    s["field_errors"].append(f"row {t['n']}: crossed-out line used")
            continue
        s["rows_expected"] += 1
        if best is None:
            s["field_errors"].append(f"row {t['n']}: not found")
            continue
        p = parsed[best]
        s["rows_found"] += 1
        flagged = set(p.get("unreadable") or [])
        for field in G3_FIELDS:
            if field in t["unreadable"]:
                s["unreadable_expected"] += 1
                if p.get(field) is None:
                    s["unreadable_empty"] += 1
                    s["unreadable_flagged"] += field in flagged
                else:
                    s["guessed_unreadable"] += 1
                    s["field_errors"].append(f"row {t['n']}: guessed unreadable {field} as {p.get(field)!r}")
                continue
            s["false_unreadable_flags"] += field in flagged
            s["fields_checked"] += 1
            if _g3_field_ok(field, t, p.get(field)):
                s["fields_ok"] += 1
            else:
                s["field_errors"].append(f"row {t['n']}: {field} {p.get(field)!r}, expected {t[field]!r}")
        if resolved is not None and t["product"] is not None:
            got = resolved[best]
            s["resolved_checked"] += 1
            s["resolved_ok"] += got == t["product"]
            s["resolved_wrong"] += got is not None and got != t["product"]
    s["extra_rows"] = sum(1 for j in free if not parsed[j].get("crossed_out"))
    s["pass"] = (s["rows_found"] == s["rows_expected"] and not s["extra_rows"] and not s["crossed_used"]
                 and not s["guessed_unreadable"] and s["fields_ok"] >= 0.9 * s["fields_checked"])
    return s


def metrics_g3(rows):
    def total(key):
        return sum(r["score"][key] for r in rows)

    def ratio(hits, n):
        return {"n": n, "hits": hits, "rate": round(hits / n, 3) if n else None}

    return {"pass": rate(rows, "pass"),
            "row_recall": ratio(total("rows_found"), total("rows_expected")),
            "field_accuracy": ratio(total("fields_ok"), total("fields_checked")),
            "unreadable_left_empty": ratio(total("unreadable_empty"), total("unreadable_expected")),
            "unreadable_flagged": ratio(total("unreadable_flagged"), total("unreadable_expected")),
            "guessed_unreadable": total("guessed_unreadable"),
            "false_unreadable_flags": total("false_unreadable_flags"),
            "extra_rows": total("extra_rows"), "crossed_used": total("crossed_used"),
            "product_resolved": ratio(total("resolved_ok"), total("resolved_checked")),
            "product_resolved_wrong": total("resolved_wrong"),
            "by_stratum": {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in sorted({r["stratum"] for r in rows})}}


BLOCKING = ("RED",)
PREVENTABLE_STATUS = ("at_loq", "not_listed")


def score_g4(case, a):
    """Preventable lots must be RED; lots whose limit history is unknown must not be GREEN; dose-dependent lots are
    reported, not failed (a log check cannot see dose). Every RASFF-unauthorised substance should be RED."""
    t, stratum, verdict = case["truth"], case["stratum"], a["verdict"]
    subs = t["substances"]
    s = {"blocked": verdict == "RED", "warned": verdict in ("RED", "AMBER"), "abstained": verdict == "CANNOT_VERIFY",
         "green": verdict == "GREEN",
         "unauthorised_n": len(t["unauthorised"]),
         "unauthorised_red": sum(a["levels"].get(n) == "RED" for n in t["unauthorised"]),
         "unauthorised_not_green": sum(a["levels"].get(n) not in (None, "GREEN") for n in t["unauthorised"]),
         "substance_misses": [x["eu_substance"] for x in subs
                              if x["limit_status"] in PREVENTABLE_STATUS and a["levels"].get(x["eu_substance"]) != "RED"]}
    if stratum == "preventable":
        s["pass"] = s["blocked"]
        s["false_green"] = s["green"]
    elif stratum == "unknown_history":
        s["pass"] = not s["green"]
        s["false_green"] = s["green"]
    else:
        s["pass"] = True
        s["silent_green"] = s["green"]
    return s


def metrics_g4(rows):
    un = sum(r["score"]["unauthorised_n"] for r in rows)
    un_red = sum(r["score"]["unauthorised_red"] for r in rows)
    un_flag = sum(r["score"]["unauthorised_not_green"] for r in rows)
    strata = sorted({r["stratum"] for r in rows})
    return {"pass": rate(rows, "pass"),
            "blocked_all": rate(rows, "blocked"),
            "warned_all": rate(rows, "warned"),
            "blocked_preventable": rate(rows, "blocked", lambda r: r["stratum"] == "preventable"),
            "unauthorised_red": {"n": un, "hits": un_red, "rate": round(un_red / un, 3) if un else None},
            "unauthorised_not_green": {"n": un, "hits": un_flag, "rate": round(un_flag / un, 3) if un else None},
            "false_green": sum(r["score"].get("false_green", False) for r in rows),
            "substance_misses": sum(len(r["score"]["substance_misses"]) for r in rows),
            "silent_green_dose_dependent": rate(rows, "silent_green"),
            "abstained": sum(r["score"]["abstained"] for r in rows),
            "by_stratum": {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in strata},
            "blocked_by_stratum": {s: rate(rows, "blocked", lambda r, s=s: r["stratum"] == s) for s in strata}}


def score_g2s(case, a, eu):
    t = case["truth"]
    if t.get("expected") == "no_eu_substance":
        ok = not a.get("eu_substance") and a["status"] in ("cannot_verify", "not_found")
        return {"pass": ok, "wrong": bool(a.get("eu_substance")), "abstained": ok}
    if t.get("family"):
        ok = (a["status"] == "needs_confirmation" and bool(a.get("candidates"))
              and all(c.startswith(t["family"]) for c in a["candidates"]))
        ok = ok or (bool(a.get("eu_substance")) and a["eu_substance"].startswith(t["family"]))
    else:
        rec = eu.substance(t["eu_substance"])
        truth_residues = set(eu.residue_ids(rec)) if rec else set()
        same_name = a.get("eu_substance") == t["eu_substance"]
        same_residue = bool(truth_residues & set(a.get("residue_ids") or [])) and t.get("accept_same_residue", False)
        ok = bool(a.get("eu_substance")) and (same_name or same_residue)
    confident = a["status"] in ("exact", "resolved")
    return {"pass": ok, "wrong": confident and not ok, "abstained": not a.get("eu_substance") and a["status"] != "needs_confirmation"}


def metrics_g2s(rows):
    return {"pass": rate(rows, "pass"), "confident_wrong": sum(r["score"]["wrong"] for r in rows),
            "abstained": sum(r["score"]["abstained"] for r in rows),
            "by_stratum": {s: rate(rows, "pass", lambda r, s=s: r["stratum"] == s) for s in sorted({r["stratum"] for r in rows})}}


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
         "dar_accuracy": rate(rows, "dar_ok"), "fake_accepted": sum(r["score"].get("false_accept", False) for r in rows),
         "right_first_suggestion": rate(rows, "first_suggestion_ok")}
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
        if k.endswith("by_stratum"):
            continue
        lines.append(f"| {k} | {fmt_rate(v) if isinstance(v, dict) else v} |")
    lines += ["", "| Stratum | Pass |", "|---|---|"] + [f"| {s} | {fmt_rate(v)} |" for s, v in m["by_stratum"].items()]
    failures = [c for c in run["cases"] if not c["score"]["pass"]]
    lines += ["", f"## Failures ({len(failures)})", ""]
    if not failures:
        lines.append("None.")
    for c in failures:
        q, t, a = c["question"], c["truth"], c["answer"]
        bad_flags = ("false_green", "missed_red", "wrong_product", "false_accept", "over_abstain", "abstained", "wrong")
        failed = ", ".join([k for k, v in c["score"].items() if k.endswith("_ok") and v is False] +
                           [k for k, v in c["score"].items() if k in bad_flags and v])
        if run["suite"] == "g3":
            lines.append(f"- `{c['id']}` [{c['stratum']}] {q['image']} ({', '.join(t.get('defects') or []) or 'no defects'}): "
                         f"{c['score']['rows_found']}/{c['score']['rows_expected']} rows, extra {c['score']['extra_rows']}, "
                         f"crossed used {c['score']['crossed_used']}; " + "; ".join(c["score"]["field_errors"][:6]))
        elif run["suite"] == "g4":
            lines.append(f"- `{c['id']}` [{c['stratum']}] {q['reference']} {q['product_as_notified']!r} from {q['origin']} "
                         f"({q['notified_on']}): got {a['verdict']}; " + "; ".join(
                             f"{x['eu_substance']} limit {x['limit_status']}, rules {a['levels'].get(x['eu_substance'])} "
                             f"{a['codes'].get(x['eu_substance'])}" for x in t["substances"]))
        elif run["suite"] == "g6":
            lines.append(f"- `{c['id']}` [{c['stratum']}] {q['failing_product']} on {q['crop']} (harvest {q['harvest_on']}, "
                         f"spray from {q['not_before']}): {len(t['safe_products'])} safe; shown "
                         f"{[o['product'] for o in a['shown']]}; {a['trace'].get('reason', '')}")
        elif run["suite"] == "g2b":
            lines.append(f"- `{c['id']}` [{c['stratum']}] {q['trade_name']!r} ({q['country']}): expected {t['status']} "
                         f"{t.get('trade_name') or ''} {t.get('eu_substances') or ''}, got {a['status']} {a.get('trade_name') or ''} "
                         f"{a.get('eu_substances') or ''}; failed: {failed}")
        elif run["suite"] == "g2s":
            lines.append(f"- `{c['id']}` {q['label_name']!r}: expected {t['eu_substance']}, got {a['status']} {a.get('eu_substance')}; "
                         f"{(a.get('trace') or {}).get('reason', '')}")
        elif run["suite"] == "g1":
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
                        ("g2", ["pass", "product_identified", "wrong_product", "abstained_on_real", "right_first_suggestion", "registration_accuracy", "dar_accuracy", "fake_accepted"]),
                        ("g2b", ["pass", "product_identified", "substances_exact", "wrong_product", "abstained_on_real", "fake_accepted"]),
                        ("g2s", ["pass", "confident_wrong", "abstained"]),
                        ("g3", ["pass", "row_recall", "field_accuracy", "unreadable_left_empty", "guessed_unreadable", "extra_rows", "crossed_used", "product_resolved"]),
                        ("g4", ["pass", "blocked_all", "warned_all", "blocked_preventable", "unauthorised_red", "unauthorised_not_green", "false_green", "substance_misses", "silent_green_dose_dependent"]),
                        ("g6", ["pass", "coverage", "shown_unsafe", "unsafe_proposal_rate", "rejected_by_verifier"])):
        rows = [r for r in runs if r["suite"] == suite]
        if not rows:
            continue
        lines += [f"## {suite.upper()}", "", "| Config | Split | Code | " + " | ".join(keys) + " |", "|---" * (len(keys) + 3) + "|"]
        for r in rows:
            vals = [fmt_rate(r["metrics"][k]) if isinstance(r["metrics"].get(k), dict) else str(r["metrics"].get(k, "n/a")) for k in keys]
            lines.append(f"| {r['config']} | {r['split']} | {r['code_version']} | " + " | ".join(vals) + " |")
        lines.append("")
    (RESULTS / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=list(SUITES))
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

    if a.suite == "g1":
        answer, scorer, metrics = system.answer_g1, score_g1, metrics_g1
    elif a.suite == "g2":
        answer, scorer, metrics = system.answer_g2, score_g2, metrics_g2
    elif a.suite == "g2b":
        answer, scorer, metrics = system.answer_g2b, score_g2b, metrics_g2b
    elif a.suite == "g3":
        answer, scorer, metrics = system.answer_g3, score_g3, metrics_g3
    elif a.suite == "g4":
        answer, scorer, metrics = system.answer_g4, score_g4, metrics_g4
    elif a.suite == "g6":
        answer, scorer, metrics = system.answer_g6, score_g6, metrics_g6
    else:
        answer, metrics = system.answer_g2s, metrics_g2s
        scorer = lambda case, ans: score_g2s(case, ans, system.eu)  # noqa: E731
    t0, cases = time.time(), []
    for case in load(a.suite, a.split):
        t = time.time()
        try:
            ans = answer(case["question"])
        except (NotImplementedError, MissingKey) as e:
            print(f"skipped: {e}")
            return 2
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
