"""Systems under evaluation. Each answers G1 and G2 questions with a plain dict.

rules-only    deterministic baseline: EU snapshot + ONSSA cache + crop map + rules engine, no model, no web
closed-book   Nemotron answers from memory (needs NEBIUS_API_KEY)                       -- not built yet
tavily-only   Nemotron with Tavily search, no EU snapshot or ONSSA access (needs both keys) -- not built yet
full          Nemotron agent with all tools, rules engine as verifier (needs both keys)  -- not built yet

G1 answer: {eu_substance, crop_code, mrl_mg_per_kg, at_loq, no_mrl_required, verdict, cost_usd, trace}
G2 answer: {status, trade_name, substances_fr, crop_code, registered_for_crop, registration_status, dar_days, cost_usd, trace}
"""
import datetime
import os
import re

from residuecheck.crops import load_map, registration
from residuecheck.eu_data import Snapshot, norm_residue
from residuecheck.onssa import DATA, Onssa, norm
from residuecheck.rules import Application, Level, Lot, evaluate


class MissingKey(RuntimeError):
    pass


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
            return {"status": "not_found", "trade_name": None, "substances_fr": [], "crop_code": crop,
                    "registered_for_crop": None, "registration_status": None, "dar_days": None, "cost_usd": 0.0,
                    "trace": {"lookup_status": rec.get("status"), "suggestions": rec.get("suggestions", [])}}
        reg = registration(rec, crop, self.eu, self.crop_map) if crop else None
        return {"status": "found", "trade_name": rec["trade_name"], "substances_fr": [s["name_fr"] for s in rec["substances"]],
                "crop_code": crop, "registered_for_crop": reg.registered_for_crop if reg else None,
                "registration_status": reg.status if reg else None, "dar_days": reg.dar_days if reg else None,
                "cost_usd": 0.0, "trace": {"note": reg.note if reg else "crop not resolved"}}


class _NeedsModel:
    keys = ("NEBIUS_API_KEY",)

    def __init__(self, snapshot="2026-09-13"):
        missing = [k for k in self.keys if not os.environ.get(k)]
        if missing:
            raise MissingKey(f"{self.name} needs {', '.join(missing)}")
        raise NotImplementedError(f"{self.name} is not built yet (planned once the keys work)")


class ClosedBook(_NeedsModel):
    name = "closed-book"
    description = "Nemotron 3 Super answers from memory, no tools"


class TavilyOnly(_NeedsModel):
    name = "tavily-only"
    description = "Nemotron with Tavily search and extract; no EU snapshot or ONSSA access"
    keys = ("NEBIUS_API_KEY", "TAVILY_API_KEY")


class Full(_NeedsModel):
    name = "full"
    description = "Nemotron agent with EU snapshot, ONSSA, Tavily; rules engine verifies"
    keys = ("NEBIUS_API_KEY", "TAVILY_API_KEY")


SYSTEMS = {s.name: s for s in (RulesOnly, ClosedBook, TavilyOnly, Full)}
