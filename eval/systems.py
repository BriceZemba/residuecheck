"""Systems under evaluation. Each answers G1 and G2 questions with a plain dict.

rules-only    deterministic baseline: EU snapshot + ONSSA cache + crop map + rules engine, exact names only
rules-fuzzy   rules-only + fuzzy ONSSA name suggestions (deterministic resolver, no model)
full          resolver agent (Nemotron on Token Factory + Tavily) with the verifier, then the rules engine
no-tavily     full without web search (isolates Tavily's contribution)
closed-book   Nemotron answers from memory, no tools (G6 only so far)
no-verifier   full with the verifier switched off (G6 only so far)

G1 answer:  {eu_substance, crop_code, mrl_mg_per_kg, at_loq, no_mrl_required, verdict, cost_usd, trace}
G2 answer:  {status, trade_name, suggestions, substances_fr, crop_code, registered_for_crop, registration_status, dar_days, cost_usd, trace}
G2b answer: {status, trade_name, eu_substances, evidence_url, cost_usd, trace}
G2s answer: {status, eu_substance, residue_ids, candidates, cost_usd, trace}
G3 answer:  {rows: [{date, product, dose, target, crossed_out, unreadable}], resolved: [ONSSA name or None per row],
             problems, cost_usd, trace}
G5 answer:  the /api/check response (verdict, applications, findings, alternatives, csv_errors) plus cost_usd
G4 answer:  {verdict, levels: {eu_substance: level}, codes: {eu_substance: [codes]}, cost_usd, trace}
G6 answer:  {status, shown: [{product, spray_on}], proposed: [{product, spray_on}], rejected, cost_usd, trace}

G4 gives resolved substances, so every configuration that reaches the rules engine answers it the same way; it is
run with rules-only. Model-only configurations (closed-book, no-verifier) do not answer it.
"""
import datetime
import pathlib
import re

from residuecheck.alternatives import Alternatives
from residuecheck.crops import load_map, registration
from residuecheck.engine import RULES_NOTE, Engine
from residuecheck.eu_data import Snapshot, norm_residue
from residuecheck.logparse import LogParser, vision_model
from residuecheck.onssa import DATA, Onssa, norm
from residuecheck.resolver import Resolver
from residuecheck.rules import Application, Level, Lot, evaluate
from residuecheck.search import MissingKey, default_search


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _clean(name):
    return re.sub(r"^\(?[a-z]\)\s*", "", name or "").strip()


class RulesOnly:
    name = "rules-only"
    description = "EU snapshot + ONSSA cache + crop map + rules engine; exact-name lookups only; no model, no web"

    def __init__(self, snapshot="2026-09-13"):
        self.eu = Snapshot(snapshot)
        self.crop_map = load_map()
        self.onssa = Onssa(list_file=DATA / "onssa_products_2026-09-14.json")
        self.crop_index = self._crop_index()

    def _crop_index(self):
        """Crop names people use -> snapshot crop code: EN, FR and synonym first forms. Collisions resolve to None."""
        index = {}

        def add(text, code):
            key = norm_residue(_clean(text))
            if key:
                index[key] = code if index.get(key, code) == code else None

        for code, raw in self.eu.crops.items():
            p = self.eu.products.get(code, {})
            for text in (raw, p.get("EN"), p.get("FR")):
                add(text, code)
                for part in (text or "").split("/"):
                    add(part, code)
            for syn in (p.get("synonyms") or "").split(","):
                add(syn.split("/")[0], code)
        return index

    def crop_code(self, text):
        return self.crop_index.get(norm_residue(_clean(text)))

    def answer_g1(self, q):
        date = datetime.date.fromisoformat(q["date"])
        crop = self.crop_code(q["crop"])
        sub = self.eu.substance(q["substance"])
        trace = {"crop_code": crop, "substance": sub["substance_name"] if sub else None}
        empty = {"eu_substance": trace["substance"], "crop_code": crop, "mrl_mg_per_kg": None, "at_loq": None,
                 "no_mrl_required": None, "verdict": Level.CANNOT_VERIFY.name, "cost_usd": 0.0, "trace": trace}
        if crop is None or sub is None:
            return empty
        rids = self.eu.residue_ids(sub)
        mrl = self.eu.mrl_on(rids[0], crop, date) if len(rids) == 1 else None
        lot = Lot(crop, date - datetime.timedelta(10),
                  [Application(q["substance"], date - datetime.timedelta(40), [sub["substance_name"]], True, 0)], arrival_on=date)
        result = evaluate(lot, self.eu)
        trace["codes"] = sorted({f.code for f in result.findings if f.level > Level.INFO})
        return {**empty, "mrl_mg_per_kg": mrl.value if mrl else None, "at_loq": mrl.at_loq if mrl else None,
                "no_mrl_required": mrl.no_mrl_required if mrl else None, "verdict": result.verdict.name, "trace": trace}

    def answer_g2(self, q):
        crop = self.crop_code(q["crop"])
        rec = self.onssa.lookup(q["trade_name"], offline=True)
        if rec.get("status") not in ("found",) and not rec.get("from_cache"):
            return {"status": "not_found", "trade_name": None, "suggestions": rec.get("suggestions", []), "substances_fr": [], "crop_code": crop,
                    "registered_for_crop": None, "registration_status": None, "dar_days": None, "cost_usd": 0.0,
                    "trace": {"lookup_status": rec.get("status"), "suggestions": rec.get("suggestions", [])}}
        reg = registration(rec, crop, self.eu, self.crop_map) if crop else None
        return {"status": "found", "trade_name": rec["trade_name"], "suggestions": [], "substances_fr": [s["name_fr"] for s in rec["substances"]],
                "crop_code": crop, "registered_for_crop": reg.registered_for_crop if reg else None,
                "registration_status": reg.status if reg else None, "dar_days": reg.dar_days if reg else None,
                "cost_usd": 0.0, "trace": {"note": reg.note if reg else "crop not resolved"}}

    def answer_g2b(self, q):
        # No Turkish or Egyptian register data without web search: the honest answer is "cannot verify".
        return {"status": "cannot_verify", "trade_name": None, "eu_substances": [], "evidence_url": None,
                "cost_usd": 0.0, "trace": {"reason": "no register data for this country without the resolver agent"}}

    def answer_g2s(self, q):
        rec = self.eu.substance(q["label_name"])
        return {"status": "exact" if rec else "cannot_verify", "eu_substance": rec["substance_name"] if rec else None,
                "residue_ids": self.eu.residue_ids(rec) if rec else [], "candidates": [], "cost_usd": 0.0, "trace": {}}


    def answer_g3(self, q):
        raise NotImplementedError(f"{self.name} has no vision model; G3 runs with full / no-tavily once one is chosen (S1)")

    def g5_engine(self):
        return Engine("rules", note=RULES_NOTE)

    def answer_g5(self, q):
        """The whole product path: the same API call the web app makes, with this system's engine."""
        from residuecheck import api

        api.set_engine(self.g5_engine())
        fields = {k: v for k, v in q.items() if k != "kind"}
        body = api.check_csv(api.CsvCheckRequest(**fields)) if q["kind"] == "csv" else api.check(api.CheckRequest(**fields))
        cost = sum((a.get("resolution") or {}).get("cost_usd") or 0 for a in body["applications"])
        return {**body, "cost_usd": cost}

    def answer_g4(self, q):
        # The notification date stands in for EU arrival; spray and harvest are placed well before it so only the
        # limit matters (registered, zero-day interval), as in G1.
        day = datetime.date.fromisoformat(q["notified_on"])
        apps = [Application(s, day - datetime.timedelta(40), [s], True, 0) for s in q["substances"]]
        result = evaluate(Lot(q["crop_code"], day - datetime.timedelta(10), apps, arrival_on=day), self.eu)
        levels, codes = {}, {}
        for s in q["substances"]:
            mine = [f for f in result.findings if f.product == s and f.level > Level.INFO]
            levels[s] = max((f.level for f in mine), default=Level.GREEN).name
            codes[s] = sorted({f.code for f in mine})
        return {"verdict": result.verdict.name, "levels": levels, "codes": codes, "cost_usd": 0.0, "trace": {}}

    def _plan_answer(self, alt, q):
        plan = alt.plan(q["failing_product"], q["crop_code"], q["harvest_on"], q["not_before"])
        return {"status": plan.status,
                "shown": [{"product": o.product, "spray_on": o.spray_on.isoformat() if o.spray_on else None} for o in plan.options],
                "proposed": plan.proposed, "rejected": len(plan.rejected), "cost_usd": plan.cost_usd,
                "trace": {"reason": plan.reason, "rejected": plan.rejected, "steps": plan.trace}}

    def answer_g6(self, q):
        return self._plan_answer(Alternatives(self.eu, self.crop_map), q)


class RulesFuzzy(RulesOnly):
    name = "rules-fuzzy"
    description = "rules-only plus fuzzy ONSSA name suggestions with a clear margin; no model, no web"

    def __init__(self, snapshot="2026-09-13"):
        super().__init__(snapshot)
        self.resolver = Resolver(self.eu, self.onssa)

    def answer_g2(self, q):
        res = self.resolver.product(q["trade_name"])
        if res.status == "exact":
            return super().answer_g2({**q, "trade_name": res.value})
        base = super().answer_g2(q)
        return {**base, "status": "suggested" if res.status == "suggested" else "not_found",
                "suggestions": res.candidates, "trace": {"resolver": res.status, "reason": res.reason}}


class Full(RulesOnly):
    name = "full"
    description = "Resolver agent (Nemotron on Token Factory + Tavily) with deterministic verifier, then rules engine"
    use_search = True

    def __init__(self, snapshot="2026-09-13"):
        super().__init__(snapshot)
        from residuecheck.llm import TokenFactory

        self.model = TokenFactory()  # raises MissingKey until Token Factory billing works
        self.search = default_search() if self.use_search else None
        self.resolver = Resolver(self.eu, self.onssa, model=self.model, search=self.search)

    def answer_g2(self, q):
        res = self.resolver.product(q["trade_name"])
        if res.confirmed:
            out = super().answer_g2({**q, "trade_name": res.value})
        else:
            out = {**super().answer_g2({**q, "trade_name": "__unresolved__"}),
                   "status": "suggested" if res.status == "suggested" else "not_found", "suggestions": res.candidates}
        out.update({"cost_usd": res.cost_usd, "trace": {"resolver": res.status, "reason": res.reason, "steps": res.trace}})
        return out

    def answer_g2b(self, q):
        res = self.resolver.product(q["trade_name"], country=q["country"])
        return {"status": res.status, "trade_name": res.value, "eu_substances": res.substances,
                "evidence_url": res.evidence[0]["url"] if res.evidence else None, "cost_usd": res.cost_usd,
                "trace": {"reason": res.reason, "steps": res.trace}}

    def answer_g2s(self, q):
        res = self.resolver.substance(q["label_name"])
        return {"status": res.status, "eu_substance": res.value, "residue_ids": res.residue_ids, "candidates": res.candidates,
                "cost_usd": res.cost_usd, "trace": {"reason": res.reason, "steps": res.trace}}

    def answer_g6(self, q):
        return self._plan_answer(Alternatives(self.eu, self.crop_map, model=self.model), q)

    def g5_engine(self):
        return Engine("live", self.model, self.search, daily_usd=1e9, note=self.description)

    def answer_g3(self, q):
        out = LogParser(vision_model()).parse(ROOT / q["image"], q.get("crop_hint"))
        resolved, cost, steps = [], out["cost_usd"], []
        for r in out["rows"]:
            if not r["product"]:
                resolved.append(None)
                continue
            res = self.resolver.product(r["product"])
            resolved.append(res.value if res.confirmed else None)
            cost += res.cost_usd
            steps.append({"product": r["product"], "status": res.status, "reason": res.reason})
        return {"rows": out["rows"], "resolved": resolved, "problems": out["problems"], "cost_usd": cost,
                "trace": {"vision_model": out["model"], "resolver": steps}}

    def answer_g1(self, q):
        if self.eu.substance(q["substance"]) is None:
            res = self.resolver.substance(q["substance"])
            if res.confirmed:
                ans = super().answer_g1({**q, "substance": res.value})
                return {**ans, "cost_usd": res.cost_usd, "trace": {**ans["trace"], "resolver": res.reason}}
        return super().answer_g1(q)


class NoTavily(Full):
    name = "no-tavily"
    description = "full without web search: isolates what Tavily contributes"
    use_search = False


class ClosedBook(RulesOnly):
    name = "closed-book"
    description = "Nemotron 3 Super answers from memory, no tools; its answers still pass through the verifier"

    def __init__(self, snapshot="2026-09-13"):
        super().__init__(snapshot)
        from residuecheck.llm import TokenFactory

        self.model = TokenFactory()

    def answer_g6(self, q):
        return self._plan_answer(Alternatives(self.eu, self.crop_map, model=self.model, use_tools=False), q)

    def answer_g1(self, q):
        raise NotImplementedError("closed-book is only built for G6 so far")

    answer_g2 = answer_g2b = answer_g2s = answer_g3 = answer_g4 = answer_g5 = answer_g1


class NoVerifier(Full):
    name = "no-verifier"
    description = "full with the verifier switched off (G6 only so far)"

    def answer_g6(self, q):
        return self._plan_answer(Alternatives(self.eu, self.crop_map, model=self.model, verify=False), q)

    def answer_g1(self, q):
        raise NotImplementedError("no-verifier is only built for G6 so far")

    answer_g2 = answer_g2b = answer_g2s = answer_g3 = answer_g4 = answer_g5 = answer_g1


SYSTEMS = {s.name: s for s in (RulesOnly, RulesFuzzy, Full, NoTavily, ClosedBook, NoVerifier)}
