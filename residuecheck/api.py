"""HTTP API for the ResidueCheck web app.

Products are resolved cheapest first: exact ONSSA name, then a clearly closest name (a suggestion the user confirms),
then the resolver agent. Verdicts always come from the rules engine. Which agent runs (live, replayed recording, or
none) is chosen by residuecheck/engine.py; every response says which engine produced it, and when an input fell
back to fixed rules.

Run:  uvicorn residuecheck.api:app --reload --port 8000
"""
import csv
import datetime
import io
import json
import mimetypes
import pathlib
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from residuecheck.alternatives import Alternatives
from residuecheck.engine import Engine, from_env
from residuecheck.crops import load_map, registration
from residuecheck.eu_data import Snapshot
from residuecheck.onssa import DATA, Onssa
from residuecheck.replay import ReplayMiss
from residuecheck.resolver import Resolver
from residuecheck.rules import Application, Finding, Level, Lot, evaluate

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "web" / "dist"
ONSSA_LIST = DATA / "onssa_products_2026-09-14.json"
NOT_RECORDED = "This input is not in the recorded demo, so it was checked by fixed rules only (no model call)."
OVER_BUDGET = "Today's model budget for this demo is used up, so this input was checked by fixed rules only."
HEADLINES = {
    Level.RED: "Do not ship this lot to the EU as planned.",
    Level.CANNOT_VERIFY: "This lot cannot be confirmed safe to ship yet.",
    Level.AMBER: "Shippable, with risks to check first.",
    Level.GREEN: "No rule-based red flags for the EU.",
}
MAX_APPLICATIONS = 40

mimetypes.add_type("image/webp", ".webp")  # missing from some systems' tables (Windows): photos would go out as text/plain
app = FastAPI(title="ResidueCheck API", version="0.1.0")


@lru_cache(maxsize=1)
def eu():
    return Snapshot()


@lru_cache(maxsize=1)
def crop_map():
    return load_map()


_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = from_env()
    return _engine


def set_engine(value: Engine):
    """Swap the engine (tests, or a server that configures it explicitly)."""
    global _engine
    _engine = value
    resolver_agent.cache_clear()
    alternatives_agent.cache_clear()


@lru_cache(maxsize=1)
def alternatives():
    return Alternatives(eu(), crop_map())


@lru_cache(maxsize=1)
def alternatives_agent():
    return Alternatives(eu(), crop_map(), model=engine().model)


@lru_cache(maxsize=1)
def resolver_rules():
    return Resolver(eu(), onssa())


@lru_cache(maxsize=1)
def resolver_agent():
    return Resolver(eu(), onssa(), model=engine().model, search=engine().search)


def fallback_note(eng):
    return NOT_RECORDED if eng.mode == "replay" else OVER_BUDGET


def plan_alternatives(trade_name, crop_code, harvest_on, not_before):
    """Agent plan when an agent is available (its proposals pass the same verifier), else the fixed-rules plan."""
    eng, note = engine(), None
    if eng.agent_allowed():
        try:
            plan = alternatives_agent().plan(trade_name, crop_code, harvest_on, not_before)
            eng.spend(plan.cost_usd)
            return plan, "agent", None
        except ReplayMiss:
            note = NOT_RECORDED
    elif eng.model is not None:
        note = OVER_BUDGET
    return alternatives().plan(trade_name, crop_code, harvest_on, not_before), "rules", note


REPLACEABLE = {"MRL_AT_LOQ", "MRL_DEFAULT", "NOT_REGISTERED_FOR_CROP", "PHI_NOT_MET"}


def safer_options(item, findings, crop_code, harvest_on, today):
    """Deterministic safe alternatives for a product that blocks the lot, with the right framing:
    a planned spray can be replaced; an applied one cannot be undone (options are for the next spray)."""
    codes = {f.code for f in findings if f.product == item["trade_name"]}
    blocking = codes & REPLACEABLE
    if not blocking or item["status"] != "found":
        return None
    applied_on = datetime.date.fromisoformat(item["applied_on"])
    planned = applied_on >= today
    if not planned and blocking == {"PHI_NOT_MET"}:
        return None  # already sprayed: the answer is the later harvest date, shown in the verdict
    not_before = applied_on if planned else today
    if not_before >= harvest_on:
        return None
    plan, method, fallback = plan_alternatives(item["trade_name"], crop_code, harvest_on, not_before)
    return {
        "method": method,
        "replayed": method == "agent" and engine().mode == "replay",
        "fallback_note": fallback,
        "rejected": [{"product": r.get("product"), "why": r.get("why")} for r in plan.rejected][:10]
        if method == "agent" else [],
        "context": "planned" if planned else "applied",
        "note": ("Replace this planned spray with one of these." if planned else
                 "This spray is already done and cannot be undone; a residue test before shipping is advisable. "
                 "For the next spray against the same pest before this harvest:"),
        "not_before": not_before.isoformat(),
        "status": plan.status,
        "reason": plan.reason,
        "options": [{"product": o.product, "substances": o.substances, "pests": o.pests, "dar_days": o.dar_days,
                     "spray_on": o.spray_on.isoformat() if o.spray_on else None,
                     "latest_spray": o.latest_spray.isoformat() if o.latest_spray else None,
                     "why": o.why, "source": o.source} for o in plan.options],
    }


@lru_cache(maxsize=1)
def onssa():
    return Onssa(list_file=ONSSA_LIST)


class SprayRow(BaseModel):
    product: str = Field(min_length=1, max_length=120)
    applied_on: datetime.date


class CheckRequest(BaseModel):
    crop_code: str
    harvest_on: datetime.date
    arrival_on: datetime.date | None = None
    today: datetime.date | None = None  # reference date for "already sprayed" vs "planned"; defaults to the server date
    origin: str = "MA"
    applications: list[SprayRow] = Field(min_length=1, max_length=MAX_APPLICATIONS)

    @field_validator("origin")
    @classmethod
    def morocco_only(cls, v):
        if v != "MA":
            raise ValueError("only origin MA (Morocco) is supported in this version")
        return v


class CsvCheckRequest(BaseModel):
    crop_code: str
    harvest_on: datetime.date
    arrival_on: datetime.date | None = None
    today: datetime.date | None = None
    origin: str = "MA"
    csv_text: str = Field(min_length=1, max_length=20000)


def _cached(name):
    rec = onssa().lookup(name, offline=True)
    return rec if rec.get("status") == "found" or rec.get("from_cache") else None


def resolve(product):
    """-> (status, ONSSA record or None, suggestions, how it was resolved). Never guesses: a close name is only a
    suggestion, and an agent answer counts only if the verifier accepted it."""
    rec = onssa().lookup(product, offline=True)
    if rec.get("status") == "found" or rec.get("from_cache"):
        return "found", rec, [], {"method": "exact", "status": "exact", "reason": "exact name in the ONSSA index"}
    if rec.get("status") == "not_cached":
        return "not_cached", None, [rec.get("trade_name")], {"method": "exact", "status": "not_cached", "reason": ""}
    suggestions = rec.get("suggestions", [])
    fixed = resolver_rules().product(product)
    if fixed.status == "suggested":
        suggestions = [fixed.value] + [s for s in suggestions if s != fixed.value]
    suggestions = suggestions or fixed.candidates[:3]
    how = {"method": "rules", "status": fixed.status, "reason": fixed.reason}
    eng = engine()
    if fixed.status == "suggested" or eng.model is None:
        return "not_found", None, suggestions, how
    if not eng.agent_allowed():
        return "not_found", None, suggestions, {**how, "note": OVER_BUDGET}
    try:
        res = resolver_agent().product(product)
    except ReplayMiss:
        return "not_found", None, suggestions, {**how, "note": NOT_RECORDED}
    eng.spend(res.cost_usd)
    how = {"method": "agent", "replayed": eng.mode == "replay", "status": res.status, "reason": res.reason,
           "evidence": res.evidence[:3], "model_calls": res.model_calls, "cost_usd": round(res.cost_usd, 5),
           "rejected": [s.get("why") for s in res.trace if s.get("type") == "verifier" and s.get("decision") == "rejected"],
           "tools_used": [s["name"] for s in res.trace if s.get("type") == "tool"]}
    if res.confirmed:
        found = _cached(res.value)
        if found:
            return "found", found, [], how
        return "not_cached", None, [res.value], how
    return "not_found", None, res.candidates or suggestions, how


def run_check(crop_code, harvest_on, arrival_on, rows, today=None, unreadable=()):
    snapshot = eu()
    if crop_code not in snapshot.crops:
        raise HTTPException(422, f"unsupported crop code {crop_code}")
    apps, resolutions = [], []
    for row in rows:
        status, rec, suggestions, how = resolve(row.product)
        item = {"input": row.product, "applied_on": row.applied_on.isoformat(), "status": status,
                "suggestions": suggestions, "trade_name": None, "substances": [], "registration": None,
                "dar_days": None, "source": None, "resolution": how}
        if rec is None:
            apps.append(Application(row.product, row.applied_on, []))
        else:
            reg = registration(rec, crop_code, snapshot, crop_map())
            subs = [s["name_fr"] for s in rec["substances"]]
            item.update({"trade_name": rec["trade_name"], "registration_no": rec.get("registration_no"),
                         "substances": [{"name": s["name_fr"], "content": s["content"],
                                         "eu_name": (snapshot.substance(s["name_fr"]) or {}).get("substance_name")}
                                        for s in rec["substances"]],
                         "registration": reg.status, "registration_note": reg.note,
                         "matched_usages": sorted({u["crop_fr"] for u in reg.matched_usages}),
                         "dar_days": reg.dar_days, "source": rec.get("source"), "retrieved": rec.get("retrieved")})
            apps.append(Application(rec["trade_name"], row.applied_on, subs, reg.registered_for_crop, reg.dar_days,
                                    rec.get("source"), reg.note))
        resolutions.append(item)

    lot = Lot(crop_code, harvest_on, apps, arrival_on=arrival_on)
    result = evaluate(lot, snapshot)
    if unreadable:
        # A spray line that could not be read is a spray we know nothing about: the lot cannot be confirmed.
        result.findings.append(Finding("LOG_LINE_UNREADABLE", Level.CANNOT_VERIFY,
                                       f"{len(unreadable)} line(s) of the spray log could not be read ({'; '.join(unreadable)}). "
                                       "Fix them so every spray is checked; until then the lot cannot be confirmed."))
        result.verdict = max(result.verdict, Level.CANNOT_VERIFY)
    today = today or datetime.date.today()
    for item in resolutions:
        item["alternatives"] = safer_options(item, result.findings, crop_code, harvest_on, today)
    findings = [{"level": f.level.name, "code": f.code, "message": f.message, "product": f.product,
                 "substance": f.substance, "sources": f.sources} for f in sorted(result.findings, key=lambda f: -f.level)]
    return {
        "verdict": result.verdict.name,
        "headline": HEADLINES[result.verdict],
        "earliest_safe_harvest": result.earliest_safe_harvest.isoformat() if result.earliest_safe_harvest else None,
        "crop": {"code": crop_code, "name": snapshot.crops[crop_code]},
        "harvest_on": harvest_on.isoformat(),
        "arrival_on": lot.arrival_on.isoformat(),
        "today": today.isoformat(),
        "applications": resolutions,
        "findings": findings,
        "counts": {lvl.name: sum(f.level == lvl for f in result.findings) for lvl in Level},
        "assumptions": result.assumptions,
        "engine": engine().info(),
        "data": {"eu_snapshot": snapshot.date.isoformat(), "onssa_index_updated": onssa().index_updated},
    }


def parse_csv(text):
    """Accept 'product,date' rows (header optional; ';' or ',' separated; dates YYYY-MM-DD or DD/MM/YYYY)."""
    dialect = ";" if text.count(";") > text.count(",") else ","
    rows, errors = [], []
    for i, cells in enumerate(csv.reader(io.StringIO(text.strip()), delimiter=dialect), start=1):
        cells = [c.strip() for c in cells if c.strip()]
        if not cells:
            continue
        if i == 1 and cells[0].lower() in ("product", "produit", "trade_name", "nom commercial"):
            continue
        if len(cells) < 2:
            errors.append(f"line {i}: expected product and date")
            continue
        raw = cells[1]
        try:
            day = datetime.date.fromisoformat(raw) if "-" in raw else datetime.datetime.strptime(raw, "%d/%m/%Y").date()
        except ValueError:
            errors.append(f"line {i}: unreadable date '{raw}'")
            continue
        rows.append(SprayRow(product=cells[0], applied_on=day))
    return rows, errors


@app.get("/api/health")
def health():
    return {"status": "ok", "engine": engine().info(), "eu_snapshot": eu().date.isoformat(),
            "onssa_index_updated": onssa().index_updated, "onssa_products": len(onssa().names()),
            "crops": len(eu().crops)}


SCENARIOS = ROOT / "data" / "demo_scenarios.json"


@app.get("/api/scenarios")
def scenarios():
    """Fixed demo lots; `recorded` says whether an agent run for it is in the replay recording."""
    eng = engine()
    recorded = set(eng.store.scenarios) if eng.store is not None else set()
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    return [{**s, "recorded": s["id"] in recorded} for s in data["scenarios"]]


@app.get("/api/crops")
def crops():
    out = []
    for code, name in eu().crops.items():
        p = eu().products.get(code, {})
        out.append({"code": code, "name": name.replace("(a) ", "").replace("(b) ", "").strip().capitalize()
                    if name.startswith("(") else name, "name_fr": p.get("FR")})
    return sorted(out, key=lambda c: c["name"].lower())


@app.get("/api/products")
def products(q: str = "", limit: int = 20):
    q = q.strip().upper()
    names = onssa().names()
    hits = [n for n in names if n.upper().startswith(q)] if q else []
    hits += [n for n in names if q and q in n.upper() and n not in hits]
    return {"products": hits[:max(1, min(limit, 50))]}


@app.post("/api/check")
def check(req: CheckRequest):
    return run_check(req.crop_code, req.harvest_on, req.arrival_on, req.applications, req.today)


@app.post("/api/check/csv")
def check_csv(req: CsvCheckRequest):
    if req.origin != "MA":
        raise HTTPException(422, "only origin MA (Morocco) is supported in this version")
    rows, errors = parse_csv(req.csv_text)
    if not rows:
        raise HTTPException(422, {"message": "no usable rows", "errors": errors})
    if len(rows) > MAX_APPLICATIONS:
        raise HTTPException(422, f"at most {MAX_APPLICATIONS} rows")
    result = run_check(req.crop_code, req.harvest_on, req.arrival_on, rows, req.today, unreadable=errors)
    result["csv_errors"] = errors
    return result


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = WEB_DIST / path
        return FileResponse(target if path and target.is_file() else WEB_DIST / "index.html")
