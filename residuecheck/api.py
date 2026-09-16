"""HTTP API for the ResidueCheck web app.

Current engine: rules-only. Products are resolved by exact name against the cached ONSSA index, verdicts come
from the rules engine. The model-based resolver and alternatives agents plug in here once Token Factory access
works; until then every response says which engine produced it.

Run:  uvicorn residuecheck.api:app --reload --port 8000
"""
import csv
import datetime
import io
import pathlib
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from residuecheck.crops import load_map, registration
from residuecheck.eu_data import Snapshot
from residuecheck.onssa import DATA, Onssa
from residuecheck.rules import Application, Level, Lot, evaluate

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "web" / "dist"
ONSSA_LIST = DATA / "onssa_products_2026-09-14.json"
ENGINE = {"name": "rules-only", "model": None,
          "note": "Preview without a language model: products are matched by exact name, verdicts come from fixed rules."}
HEADLINES = {
    Level.RED: "Do not ship this lot to the EU as planned.",
    Level.CANNOT_VERIFY: "This lot cannot be confirmed safe to ship yet.",
    Level.AMBER: "Shippable, with risks to check first.",
    Level.GREEN: "No rule-based red flags for the EU.",
}
MAX_APPLICATIONS = 40

app = FastAPI(title="ResidueCheck API", version="0.1.0")


@lru_cache(maxsize=1)
def eu():
    return Snapshot()


@lru_cache(maxsize=1)
def crop_map():
    return load_map()


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
    origin: str = "MA"
    csv_text: str = Field(min_length=1, max_length=20000)


def resolve(product):
    """Exact-name ONSSA lookup from the offline cache. Never guesses: near misses come back as suggestions."""
    rec = onssa().lookup(product, offline=True)
    if rec.get("status") == "found" or rec.get("from_cache"):
        return "found", rec, []
    if rec.get("status") == "not_cached":
        return "not_cached", None, [rec.get("trade_name")]
    return "not_found", None, rec.get("suggestions", [])


def run_check(crop_code, harvest_on, arrival_on, rows):
    snapshot = eu()
    if crop_code not in snapshot.crops:
        raise HTTPException(422, f"unsupported crop code {crop_code}")
    apps, resolutions = [], []
    for row in rows:
        status, rec, suggestions = resolve(row.product)
        item = {"input": row.product, "applied_on": row.applied_on.isoformat(), "status": status,
                "suggestions": suggestions, "trade_name": None, "substances": [], "registration": None,
                "dar_days": None, "source": None}
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
    findings = [{"level": f.level.name, "code": f.code, "message": f.message, "product": f.product,
                 "substance": f.substance, "sources": f.sources} for f in sorted(result.findings, key=lambda f: -f.level)]
    return {
        "verdict": result.verdict.name,
        "headline": HEADLINES[result.verdict],
        "earliest_safe_harvest": result.earliest_safe_harvest.isoformat() if result.earliest_safe_harvest else None,
        "crop": {"code": crop_code, "name": snapshot.crops[crop_code]},
        "harvest_on": harvest_on.isoformat(),
        "arrival_on": lot.arrival_on.isoformat(),
        "applications": resolutions,
        "findings": findings,
        "counts": {lvl.name: sum(f.level == lvl for f in result.findings) for lvl in Level},
        "assumptions": result.assumptions,
        "engine": ENGINE,
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
    return {"status": "ok", "engine": ENGINE, "eu_snapshot": eu().date.isoformat(),
            "onssa_index_updated": onssa().index_updated, "onssa_products": len(onssa().names()),
            "crops": len(eu().crops)}


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
    return run_check(req.crop_code, req.harvest_on, req.arrival_on, req.applications)


@app.post("/api/check/csv")
def check_csv(req: CsvCheckRequest):
    if req.origin != "MA":
        raise HTTPException(422, "only origin MA (Morocco) is supported in this version")
    rows, errors = parse_csv(req.csv_text)
    if not rows:
        raise HTTPException(422, {"message": "no usable rows", "errors": errors})
    if len(rows) > MAX_APPLICATIONS:
        raise HTTPException(422, f"at most {MAX_APPLICATIONS} rows")
    result = run_check(req.crop_code, req.harvest_on, req.arrival_on, rows)
    result["csv_errors"] = errors
    return result


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = WEB_DIST / path
        return FileResponse(target if path and target.is_file() else WEB_DIST / "index.html")
