"""Safe alternatives: when a product makes a lot RED, what can the grower use instead?

An option is only shown if code confirms all of this:
  - the product is registered in Morocco (ONSSA) for the lot's crop
  - it targets a pest the failing product was used against (when known)
  - it shares no active substance with the failing product
  - sprayed on the proposed date, it respects its pre-harvest interval and the lot passes the EU rules (GREEN)

Three ways to produce proposals, all checked by the same verifier:
  deterministic  enumerate registered products and keep those the rules pass (no model)
  agent          Nemotron with tools (list candidates, check an option with the rules engine) picks and explains
  closed_book    Nemotron proposes from memory, no tools: the baseline that shows why the tools and checks matter
"""
import datetime
import json
import pathlib
import unicodedata
from dataclasses import dataclass, field

from residuecheck.agent_loop import run_tool_loop
from residuecheck.crops import load_map, registration
from residuecheck.onssa import CACHE, DATA, norm
from residuecheck.rules import Application, Level, Lot, evaluate

INDEX_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "onssa_crops_index.json"
FIELD_KINDS = ("exact", "group", "narrower")
ONSSA_LIST = DATA / "onssa_products_2026-09-14.json"


def _fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _date(value):
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(value)


@dataclass
class Option:
    product: str
    substances: list[str]
    pests: list[str]
    dar_days: int | None
    latest_spray: datetime.date | None
    spray_on: datetime.date | None = None
    verdict: str | None = None
    why: str = ""
    source: str | None = None


@dataclass
class Plan:
    status: str  # deterministic | verified | none_verified | unverified | no_candidates | cannot_plan
    failing_product: str
    options: list[Option] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # [{product, spray_on, why}]
    proposed: list[dict] = field(default_factory=list)  # raw model proposals, before verification
    candidates_checked: int = 0
    reason: str = ""
    trace: list[dict] = field(default_factory=list)
    model_calls: int = 0
    cost_usd: float = 0.0


def _load_record(name):
    path = CACHE / f"{norm(name)}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Alternatives:
    def __init__(self, eu, crop_map=None, index=None, model=None, use_tools=True, max_steps=8, verify=True):
        self.eu = eu
        self.crop_map = crop_map or load_map()
        self.index = index if index is not None else (
            json.loads(INDEX_PATH.read_text(encoding="utf-8")) if INDEX_PATH.exists() else {})
        self.model = model
        self.use_tools = use_tools
        self.verify_enabled = verify  # False only for the no-verifier ablation
        self.max_steps = max_steps
        self.onssa_names = {norm(n) for n in json.loads(ONSSA_LIST.read_text(encoding="utf-8"))["products"]}             if ONSSA_LIST.exists() else set()

    # ------------------------------------------------------------ deterministic parts

    def candidate_names(self, crop_code):
        """Products listed under any indexed ONSSA crop name that covers this EU crop."""
        lineage = self.eu.lineage(crop_code)
        names = set()
        for crop_fr, entry in self.index.items():
            m = self.crop_map.get(crop_fr)
            if m and m["kind"] in FIELD_KINDS and any(c in lineage for c in m["codes"]):
                names.update(entry["products"])
        return sorted(names)

    def describe(self, record, crop_code, harvest_on):
        reg = registration(record, crop_code, self.eu, self.crop_map)
        if not reg.registered_for_crop:
            return None
        pests = sorted({u.get("pest_fr") for u in reg.matched_usages if u.get("pest_fr")})
        latest = harvest_on - datetime.timedelta(reg.dar_days) if isinstance(reg.dar_days, int) else None
        return Option(record["trade_name"], [s["name_fr"] for s in record["substances"]], pests, reg.dar_days, latest,
                      source=record.get("source"))

    def check(self, record, crop_code, spray_on, harvest_on):
        """Rules-engine verdict for spraying this product on this date. Returns (Level, [reasons])."""
        reg = registration(record, crop_code, self.eu, self.crop_map)
        subs = [s["name_fr"] for s in record["substances"]]
        lot = Lot(crop_code, harvest_on, [Application(record["trade_name"], spray_on, subs, reg.registered_for_crop,
                                                      reg.dar_days, record.get("source"), reg.note)])
        result = evaluate(lot, self.eu)
        reasons = [f"{f.code}: {f.message}" for f in result.findings if f.level > Level.INFO]
        return result.verdict, reasons

    def candidates(self, failing, crop_code, harvest_on, not_before):
        """(all registered candidates for the crop, pests of the failing product, substances to avoid)."""
        fail_opt = self.describe(failing, crop_code, harvest_on)
        target_pests = {_fold(p) for p in (fail_opt.pests if fail_opt else [])}
        avoid = {self._eu_key(s) for s in (s["name_fr"] for s in failing["substances"])}
        out = []
        for name in self.candidate_names(crop_code):
            if norm(name) == norm(failing["trade_name"]):
                continue
            rec = _load_record(name)
            if not rec or not rec.get("substances"):
                continue
            opt = self.describe(rec, crop_code, harvest_on)
            if opt is None:
                continue
            out.append((rec, opt))
        return out, target_pests, avoid

    def _eu_key(self, name):
        sub = self.eu.substance(name)
        return sub["substance_name"] if sub else _fold(name)

    def _pest_match(self, opt, target_pests):
        if not target_pests:
            return True
        mine = {_fold(p) for p in opt.pests}
        return any(a == b or a in b or b in a for a in mine for b in target_pests)

    def verify(self, failing, crop_code, harvest_on, not_before, proposals, pool):
        """Check each proposal; returns (accepted Options, rejected dicts). `pool` maps normalised name -> (record, Option)."""
        by_name, target_pests, avoid = pool
        accepted, rejected, seen = [], [], set()
        for p in proposals:
            name, why = (p.get("product") or "").strip(), p.get("why", "")
            try:
                spray_on = _date(p.get("spray_on")) if p.get("spray_on") else not_before
            except ValueError:
                rejected.append({"product": name, "spray_on": p.get("spray_on"), "why": "unreadable spray date"})
                continue
            entry = by_name.get(norm(name))

            def reject(reason):
                rejected.append({"product": name, "spray_on": spray_on.isoformat(), "why": reason})

            if norm(name) in seen:
                reject("duplicate proposal")
                continue
            if norm(name) == norm(failing["trade_name"]):
                reject("this is the product that fails")
                continue
            if entry is None:
                reject("not registered in Morocco for this crop" if norm(name) in self.onssa_names
                       else "not a product name in the ONSSA index")
                continue
            record, opt = entry
            if {self._eu_key(s) for s in opt.substances} & avoid:
                reject("contains the same active substance as the failing product")
                continue
            if not self._pest_match(opt, target_pests):
                reject(f"not registered against the same pest ({', '.join(opt.pests) or 'no pest listed'})")
                continue
            if spray_on < not_before:
                reject(f"spray date is before {not_before.isoformat()}")
                continue
            if opt.latest_spray is None:
                reject("no pre-harvest interval on the label for this crop")
                continue
            if spray_on > opt.latest_spray:
                reject(f"needs {opt.dar_days} days before harvest; latest spray date is {opt.latest_spray.isoformat()}")
                continue
            verdict, reasons = self.check(record, crop_code, spray_on, harvest_on)
            if verdict != Level.GREEN:
                reject(f"rules verdict {verdict.name}: {reasons[0] if reasons else ''}".strip())
                continue
            seen.add(norm(name))
            accepted.append(Option(opt.product, opt.substances, opt.pests, opt.dar_days, opt.latest_spray, spray_on,
                                   verdict.name, why, opt.source))
        return accepted, rejected

    # ------------------------------------------------------------------ planning

    def plan(self, failing_name, crop_code, harvest_on, not_before, max_options=3):
        harvest_on, not_before = _date(harvest_on), _date(not_before)
        failing = _load_record(failing_name)
        if failing is None:
            return Plan("cannot_plan", failing_name, reason="failing product not found in the ONSSA cache")
        cands, target_pests, avoid = self.candidates(failing, crop_code, harvest_on, not_before)
        by_name = {norm(r["trade_name"]): (r, o) for r, o in cands}
        pool = (by_name, target_pests, avoid)
        if not cands:
            return Plan("no_candidates", failing["trade_name"], reason="no registered products indexed for this crop")
        if self.model is None:
            return self._deterministic(failing, crop_code, harvest_on, not_before, cands, pool, max_options)
        return self._agent(failing, crop_code, harvest_on, not_before, cands, pool, max_options)

    def safe_set(self, failing_name, crop_code, harvest_on, not_before):
        """Every product that passes the verifier when sprayed on `not_before` (the G6 ground truth)."""
        harvest_on, not_before = _date(harvest_on), _date(not_before)
        failing = _load_record(failing_name)
        cands, target_pests, avoid = self.candidates(failing, crop_code, harvest_on, not_before)
        pool = ({norm(r["trade_name"]): (r, o) for r, o in cands}, target_pests, avoid)
        proposals = [{"product": o.product, "spray_on": not_before.isoformat()} for _, o in cands]
        accepted, _ = self.verify(failing, crop_code, harvest_on, not_before, proposals, pool)
        return sorted(o.product for o in accepted)

    def _deterministic(self, failing, crop_code, harvest_on, not_before, cands, pool, max_options):
        proposals = [{"product": o.product, "spray_on": not_before.isoformat()} for _, o in cands]
        accepted, _ = self.verify(failing, crop_code, harvest_on, not_before, proposals, pool)
        # Prefer different active substances, then the most room before harvest.
        accepted.sort(key=lambda o: (-(o.latest_spray - not_before).days, o.product))
        picked, used = [], set()
        for o in accepted:
            key = frozenset(self._eu_key(s) for s in o.substances)
            if key in used:
                continue
            used.add(key)
            o.why = f"registered against {', '.join(o.pests) or 'the same use'}; {o.dar_days} days before harvest"
            picked.append(o)
            if len(picked) == max_options:
                break
        status = "deterministic" if picked else "none_verified"
        return Plan(status, failing["trade_name"], options=picked, candidates_checked=len(cands),
                    reason=f"{len(accepted)} of {len(cands)} registered products pass the rules for this lot")

    def _agent(self, failing, crop_code, harvest_on, not_before, cands, pool, max_options):
        crop = self.eu.crops.get(crop_code, crop_code)
        fail_opt = self.describe(failing, crop_code, harvest_on)
        pests = ", ".join(fail_opt.pests) if fail_opt and fail_opt.pests else "unknown"
        system = (
            "You help a grower in Morocco replace a pesticide that would make a lot fail EU residue rules. "
            f"Propose up to {max_options} alternatives. Each must be registered in Morocco for this crop and pest, contain "
            "none of the failing product's active substances, and pass the EU rules when sprayed on the proposed date. "
            "Prefer different active substances. Never invent products."
            + (" Use the tools: list_candidates, then check_option for each product you consider." if self.use_tools else
               " You have no tools; answer from your own knowledge.")
        )
        user = (f"Crop: {crop}. Harvest on {harvest_on}. Earliest spray date: {not_before}. "
                f"Failing product: {failing['trade_name']} ({', '.join(s['name_fr'] for s in failing['substances'])}), "
                f"used against: {pests}. Submit with submit_alternatives.")
        final = {"name": "submit_alternatives", "description": "Submit the proposed alternatives.",
                 "parameters": {"type": "object", "properties": {"options": {"type": "array", "items": {
                     "type": "object", "properties": {"product": {"type": "string"}, "spray_on": {"type": "string"},
                                                      "why": {"type": "string"}}, "required": ["product"]}}},
                     "required": ["options"]}}
        by_name, target_pests, _ = pool

        def list_candidates(args, ctx):
            pest = _fold(args.get("pest") or "")
            rows = []
            for _, o in cands:
                if pest and not any(pest in _fold(p) for p in o.pests):
                    continue
                rows.append({"product": o.product, "substances": o.substances, "pests": o.pests[:6],
                             "days_before_harvest": o.dar_days,
                             "latest_spray": o.latest_spray.isoformat() if o.latest_spray else None})
            return {"candidates": rows[: int(args.get("limit") or 40)], "total": len(rows)}

        def check_option(args, ctx):
            entry = by_name.get(norm(args.get("product", "")))
            if entry is None:
                return {"verdict": "not registered for this crop"}
            spray_on = _date(args.get("spray_on") or not_before.isoformat())
            verdict, reasons = self.check(entry[0], crop_code, spray_on, harvest_on)
            return {"verdict": verdict.name, "reasons": reasons[:3]}

        tools = {}
        if self.use_tools:
            tools = {
                "list_candidates": ({"type": "object", "properties": {"pest": {"type": "string"}, "limit": {"type": "integer"}}},
                                    "Products registered in Morocco for this crop, with pests and pre-harvest interval.",
                                    list_candidates),
                "check_option": ({"type": "object", "properties": {"product": {"type": "string"}, "spray_on": {"type": "string"}},
                                  "required": ["product"]},
                                 "Run the EU rules engine for this product sprayed on this date (YYYY-MM-DD).", check_option),
            }
        run = run_tool_loop(self.model, system, user, tools, final, {}, self.max_steps)
        plan = Plan("none_verified", failing["trade_name"], candidates_checked=len(cands), trace=run["trace"],
                    model_calls=run["model_calls"], cost_usd=run["cost"])
        if run["final"] is None:
            plan.reason = run["stop_reason"]
            return plan
        proposals = (run["final"].get("options") or [])[: max_options + 2]
        plan.proposed = [{"product": p.get("product"), "spray_on": p.get("spray_on")} for p in proposals]
        if not self.verify_enabled:
            plan.options = [Option(p.get("product") or "", [], [], None, None,
                                   _date(p["spray_on"]) if p.get("spray_on") else not_before, None, p.get("why", ""))
                            for p in proposals[:max_options]]
            plan.status, plan.reason = "unverified", "verifier switched off (ablation)"
            return plan
        accepted, rejected = self.verify(failing, crop_code, harvest_on, not_before, proposals, pool)
        for r in rejected:
            plan.trace.append({"type": "verifier", "decision": "rejected", **r})
        plan.options, plan.rejected = accepted[:max_options], rejected
        plan.status = "verified" if accepted else "none_verified"
        plan.reason = f"{len(accepted)} proposal(s) passed the checks, {len(rejected)} rejected"
        return plan
