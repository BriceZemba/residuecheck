"""Spike S2: does Tavily search surface the evidence a resolver needs?

Two probes, dev cases only:
  A. The 7 G2 dev products written with a typo (C/K swap, O/0, dropped letter, missing formulation code).
     Hit = the correct ONSSA trade name appears in a top-5 result (title, URL or snippet).
  B. The 12 real label substance names the deterministic resolver cannot map (eval/gold/g2s_seed.json).
     Hit = a result contains evidence of the EU identity (e.g. "Bordeaux mixture" for
     "sulfate tétracuivrique tricalcique"). Cases where the query itself already contains the evidence
     word (echo risk) are reported separately.

Two query strategies per item. This measures retrieval only: a model still has to read the results and pick
the EU name, and the verifier still has to accept it. Uses the Tavily CLI (OAuth login) because the app's
API key is not set yet; the app will use tavily-python.

Usage: python spikes/s2_tavily.py
Writes spikes/results/s2-tavily.md (committed) and s2-tavily.raw.json (ignored).
"""
import json
import pathlib
import re
import subprocess
import sys
import time
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.onssa import norm  # noqa: E402

OUT = ROOT / "spikes" / "results"
TOP_K = 5


def fold(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text)


def tavily(query, **opts):
    cmd = ["tvly", "search", query, "--json", "--max-results", str(TOP_K)]
    for k, v in opts.items():
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()[:200], "results": [], "seconds": time.time() - t0}
    body = json.loads(proc.stdout)
    body["seconds"] = time.time() - t0
    return body


def first_hit(results, predicate):
    for rank, r in enumerate(results, start=1):
        if predicate(" ".join([r.get("title") or "", r.get("url") or "", r.get("content") or ""])):
            return rank, r["url"]
    return None, None


def probe_variants():
    cases = [json.loads(line) for line in (ROOT / "eval" / "gold" / "g2_dev.jsonl").read_text(encoding="utf-8").splitlines()]
    cases = [c for c in cases if c["stratum"] == "variant"]
    strategies = {
        "web": lambda n: dict(query=f"{n} pesticide Maroc", country="morocco"),
        "fr": lambda n: dict(query=f"{n} produit phytosanitaire homologué ONSSA"),
    }
    rows = []
    for c in cases:
        wrong, right = c["question"]["trade_name"], c["truth"]["onssa_trade_name"]
        key = norm(right)
        row = {"id": c["id"], "written": wrong, "correct": right, "kind": c["truth"]["variant_kind"]}
        for name, make in strategies.items():
            args = make(wrong)
            body = tavily(args.pop("query"), **args)
            rank, url = first_hit(body.get("results", []), lambda text: key in norm(text))
            row[name] = {"rank": rank, "url": url, "n": len(body.get("results", [])), "error": body.get("error"),
                         "seconds": round(body["seconds"], 1), "top_urls": [r["url"] for r in body.get("results", [])]}
        rows.append(row)
    return rows


def probe_substances():
    seed = json.loads((ROOT / "eval" / "gold" / "g2s_seed.json").read_text(encoding="utf-8"))["cases"]
    strategies = {
        "fr": lambda n: f"{n} matière active pesticide",
        "en": lambda n: f"{n} pesticide active substance ISO common name",
    }
    rows = []
    for c in seed:
        keywords = [fold(k) for k in c["evidence_keywords"]]
        row = {"label_name": c["label_name"], "eu_substance": c["eu_substance"], "echo_risk": c.get("echo_risk", False)}
        for name, make in strategies.items():
            query = make(c["label_name"])
            body = tavily(query)
            echo = any(k in fold(query) for k in keywords)
            rank, url = first_hit(body.get("results", []), lambda text: any(k in fold(text) for k in keywords))
            row[name] = {"rank": rank, "url": url, "echo": echo, "n": len(body.get("results", [])),
                         "error": body.get("error"), "seconds": round(body["seconds"], 1),
                         "top_urls": [r["url"] for r in body.get("results", [])]}
        rows.append(row)
    return rows


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    variants = probe_variants()
    substances = probe_substances()
    calls = 2 * (len(variants) + len(substances))

    def cell(x):
        if x["error"]:
            return f"error: {x['error'][:40]}"
        return f"#{x['rank']} {re.sub(r'^https?://(www\\.)?', '', x['url'])[:45]}" if x["rank"] else f"miss ({x['n']} results)"

    lines = ["# Spike S2 results: Tavily as evidence source for the resolver", "",
             f"Run: {time.strftime('%Y-%m-%d %H:%M')}. Tavily CLI, basic depth, top {TOP_K}. {calls} searches in {time.time() - t0:.0f} s.", "",
             "## A. Misspelled products (G2 dev variants)", "",
             "Hit = the correct ONSSA trade name appears in a top-5 result.", "",
             "| Written | Correct | Kind | `web`: name + pesticide Maroc (country=morocco) | `fr`: name + produit phytosanitaire homologué ONSSA |",
             "|---|---|---|---|---|"]
    for r in variants:
        lines.append(f"| {r['written']} | {r['correct']} | {r['kind']} | {cell(r['web'])} | {cell(r['fr'])} |")
    hit_any = sum(bool(r["web"]["rank"] or r["fr"]["rank"]) for r in variants)
    lines += ["", f"Correct name surfaced by at least one strategy: **{hit_any}/{len(variants)}** "
              f"(web {sum(bool(r['web']['rank']) for r in variants)}, fr {sum(bool(r['fr']['rank']) for r in variants)}).", "",
              "## B. Label substance names the deterministic resolver cannot map (G2s seed)", "",
              "Hit = a top-5 result contains evidence of the EU identity. `echo` = the evidence word is already in the query, so a hit proves little.", "",
              "| Label name | EU substance | `fr` query | `en` query |", "|---|---|---|---|"]
    for r in substances:
        f = cell(r["fr"]) + (" (echo)" if r["fr"]["echo"] else "")
        e = cell(r["en"]) + (" (echo)" if r["en"]["echo"] else "")
        lines.append(f"| {r['label_name']} | {r['eu_substance']} | {f} | {e} |")
    real = [r for r in substances if not (r["fr"]["echo"] and r["en"]["echo"])]
    lines += ["", f"Evidence found by at least one strategy: **{sum(bool(r['fr']['rank'] or r['en']['rank']) for r in substances)}/{len(substances)}**; "
              f"excluding cases where both queries echo the evidence: {sum(bool((r['fr']['rank'] and not r['fr']['echo']) or (r['en']['rank'] and not r['en']['echo'])) for r in real)}/{len(real)}.", ""]
    (OUT / "s2-tavily.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    (OUT / "s2-tavily.raw.json").write_text(json.dumps({"variants": variants, "substances": substances}, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
