"""Resolver: turn what is written in a spray log into verified facts.

  product(name, country)  -> which registered product is meant
  substance(label_name)   -> which EU active substance (and residue definition) a label name refers to

Order of work, cheapest and most trustworthy first:
  1. deterministic exact match (ONSSA list, EU database) -> no model call
  2. deterministic fuzzy match with a clear margin (Moroccan products) -> a suggestion the user confirms
  3. Nemotron agent with tools (register lookup, EU lookup, Tavily search and extract) -> a proposal
  4. VERIFIER (code, not model) -> accepts, downgrades to a suggestion, or rejects the proposal

The verifier only trusts text the model was actually shown during the run (search snippets and extracted pages),
never a later re-fetch, and never a URL the tools did not return. Every rejection is kept in the trace so the
interface can show what was refused and why.
"""
import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse

from residuecheck.eu_data import base_name
from residuecheck.llm import cost_usd
from residuecheck.onssa import norm

FUZZY_MIN = 0.75  # SequenceMatcher ratio on normalised names
FUZZY_MARGIN = 0.10  # best candidate must beat the runner-up by this much
OFFICIAL_DOMAINS = {
    "MA": ["eservice.onssa.gov.ma"],
    "TR": ["bku.tarimorman.gov.tr"],
    "EG": ["apc.gov.eg"],
}
MAX_TOOL_TEXT = 3000


def fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def squash(text):
    return re.sub(r"[\W_]+", "", fold(text))


@dataclass
class Resolution:
    kind: str  # "product" | "substance"
    input: str
    status: str  # exact | resolved | suggested | needs_confirmation | not_found | cannot_verify
    value: str | None = None  # trade name or EU substance name
    candidates: list[str] = field(default_factory=list)
    substances: list[str] = field(default_factory=list)  # EU names (foreign products)
    residue_ids: list[int] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)  # [{url, excerpt}]
    reason: str = ""
    trace: list[dict] = field(default_factory=list)
    model_calls: int = 0
    cost_usd: float = 0.0

    @property
    def confirmed(self):
        return self.status in ("exact", "resolved")


class Resolver:
    def __init__(self, eu, onssa, model=None, search=None, max_steps=6):
        self.eu = eu
        self.onssa = onssa
        self.model = model
        self.search = search
        self.max_steps = max_steps
        self._names = {norm(n): n for n in onssa.names()}
        self._eu_names = sorted(s["substance_name"] for s in eu.substances)

    # ------------------------------------------------------------------ products

    def fuzzy_products(self, name, k=3):
        key = norm(name)
        scored = sorted(((difflib.SequenceMatcher(None, key, n).ratio(), full) for n, full in self._names.items()), reverse=True)
        prefix = [full for n, full in self._names.items() if len(key) >= 4 and n.startswith(key)]
        return scored[:k], prefix

    def product(self, name, country="MA"):
        if country == "MA":
            return self._product_ma(name)
        return self._product_foreign(name, country)

    def _product_ma(self, name):
        if norm(name) in self._names:
            return Resolution("product", name, "exact", self._names[norm(name)], reason="exact match in the ONSSA index")
        scored, prefix = self.fuzzy_products(name)
        top = scored[0] if scored else (0, None)
        runner = scored[1][0] if len(scored) > 1 else 0
        if len(prefix) == 1:
            return Resolution("product", name, "suggested", prefix[0], [prefix[0]],
                              reason="only ONSSA product starting with this name (formulation code missing?)")
        if top[0] >= FUZZY_MIN and top[0] - runner >= FUZZY_MARGIN:
            return Resolution("product", name, "suggested", top[1], [top[1]],
                              reason=f"closest ONSSA name (similarity {top[0]:.2f}, next {runner:.2f}); confirm before use")
        candidates = [n for s, n in scored if s >= 0.6]
        if self.model is None:
            return Resolution("product", name, "not_found", None, candidates, reason="no exact or clearly closest ONSSA name")
        return self._agent_product(name, "MA", candidates)

    def _product_foreign(self, name, country):
        if self.model is None or self.search is None:
            return Resolution("product", name, "cannot_verify", reason=f"{country} products need the model and web search")
        return self._agent_product(name, country, [])

    def _agent_product(self, name, country, candidates):
        domains = OFFICIAL_DOMAINS[country]
        system = (
            "You identify pesticide products for an export compliance check. Use only facts returned by the tools. "
            f"The product must be registered in the official register for country {country} ({', '.join(domains)}). "
            "If you cannot find it with confidence, submit trade_name null. Never invent names, substances or URLs. "
            "When you submit, evidence_url must be a URL returned by a tool in this conversation."
        )
        user = (f"Spray log entry: {name!r}. Country: {country}. "
                + (f"Close names in the national register: {candidates}. " if candidates else "")
                + "Find the registered product, its active substances (EU English names, checked with eu_lookup), and submit.")
        final = {"name": "submit_product", "description": "Submit the identified product (or null).",
                 "parameters": {"type": "object", "properties": {
                     "trade_name": {"type": ["string", "null"]},
                     "active_substances": {"type": "array", "items": {"type": "string"}},
                     "evidence_url": {"type": ["string", "null"]},
                     "note": {"type": "string"}}, "required": ["trade_name"]}}
        run = self._run_agent(system, user, final, country=country)
        res = Resolution("product", name, "cannot_verify", trace=run["trace"], model_calls=run["model_calls"], cost_usd=run["cost"])
        args = run["final"]
        if args is None:
            res.reason = run["stop_reason"]
            return res
        return self._verify_product(res, args, run["seen"], country, candidates)

    def _verify_product(self, res, args, seen, country, candidates):
        proposed = args.get("trade_name")
        if not proposed:
            res.status, res.reason = ("not_found", "model found no registered product") if country == "MA" \
                else ("cannot_verify", "model found no registered product")
            res.candidates = candidates
            return res
        if country == "MA":
            if norm(proposed) not in self._names:
                return self._reject(res, f"'{proposed}' is not a name in the ONSSA index", candidates)
            res.status, res.value, res.candidates = "suggested", self._names[norm(proposed)], [self._names[norm(proposed)]]
            res.reason = "model's reading of a name that does not match exactly; confirm before use"
            return res
        url = args.get("evidence_url")
        if url not in seen:
            return self._reject(res, "evidence URL was not returned by any tool in this run", candidates)
        host = urlparse(url).hostname or ""
        if not any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS[country]):
            return self._reject(res, f"evidence is not from the official register ({host})", candidates)
        text = seen[url]
        if squash(proposed) not in squash(text):
            return self._reject(res, f"'{proposed}' does not appear on the cited register page", candidates)
        eu_names, missing = [], []
        for s in args.get("active_substances") or []:
            rec = self.eu.substance(s)
            if rec is None or squash(base_name(s)) not in squash(text):
                missing.append(s)
            else:
                eu_names.append(rec["substance_name"])
        if missing or not eu_names:
            return self._reject(res, f"substances not confirmed by the page and the EU database: {missing or 'none given'}", candidates)
        similar = difflib.SequenceMatcher(None, squash(res.input), squash(proposed)).ratio()
        res.value, res.substances = proposed, eu_names
        res.evidence = [{"url": url, "excerpt": _excerpt(text, proposed)}]
        res.status = "resolved" if similar >= 0.8 else "suggested"
        res.reason = "found on the official register page" + ("" if similar >= 0.8 else "; name differs from the log, confirm")
        return res

    # ---------------------------------------------------------------- substances

    def substance(self, label_name):
        rec = self.eu.substance(label_name)
        if rec:
            return self._substance_result(Resolution("substance", label_name, "exact", reason="matched an EU database name"), rec)
        if self.model is None or self.search is None:
            return Resolution("substance", label_name, "cannot_verify", reason="no exact EU name; needs the model and web search")
        system = (
            "You map an active-substance name printed on a pesticide label (often French, sometimes a salt or a "
            "commercial description) to the exact substance name used in the EU Pesticides Database. "
            "Search the web for evidence, then use eu_search / eu_lookup to find the exact EU spelling. "
            "Submit eu_name null if unsure. evidence_url must be a URL returned by a tool in this conversation, "
            "and the page must mention the substance you submit."
        )
        user = f"Label substance name: {label_name!r}."
        final = {"name": "submit_substance", "description": "Submit the EU substance name (or null).",
                 "parameters": {"type": "object", "properties": {
                     "eu_name": {"type": ["string", "null"]},
                     "evidence_url": {"type": ["string", "null"]},
                     "note": {"type": "string"}}, "required": ["eu_name"]}}
        run = self._run_agent(system, user, final, country=None)
        res = Resolution("substance", label_name, "cannot_verify", trace=run["trace"], model_calls=run["model_calls"], cost_usd=run["cost"])
        if run["final"] is None:
            res.reason = run["stop_reason"]
            return res
        return self._verify_substance(res, run["final"], run["seen"])

    def _verify_substance(self, res, args, seen):
        proposed = args.get("eu_name")
        if not proposed:
            res.reason = "model could not identify the substance"
            return res
        url = args.get("evidence_url")
        if url not in seen:
            return self._reject(res, "evidence URL was not returned by any tool in this run")
        text = squash(seen[url])
        rec = self.eu.substance(proposed)
        if rec is None:
            family = [n for n in self._eu_names if fold(n).startswith(fold(proposed))]
            if len(family) > 1 and squash(proposed) in text:
                res.status, res.value, res.candidates = "needs_confirmation", proposed, family
                res.evidence = [{"url": url, "excerpt": _excerpt(seen[url], proposed)}]
                res.reason = f"'{proposed}' covers {len(family)} EU entries; the label's CAS number is needed to pick one"
                return res
            return self._reject(res, f"'{proposed}' is not an EU database substance name")
        tokens = [t for t in re.split(r"[^a-z0-9]+", fold(base_name(rec["substance_name"]))) if len(t) >= 4]
        if not tokens or not all(t in text for t in tokens):
            return self._reject(res, f"the cited page does not mention {rec['substance_name']}")
        res.evidence = [{"url": url, "excerpt": _excerpt(seen[url], tokens[0])}]
        res.status = "resolved"
        res.reason = "model mapping confirmed: EU name exists and the cited page mentions it"
        return self._substance_result(res, rec)

    def _substance_result(self, res, rec):
        res.value = rec["substance_name"]
        res.residue_ids = self.eu.residue_ids(rec)
        return res

    # ------------------------------------------------------------------- shared

    def _reject(self, res, why, candidates=()):
        res.status = "cannot_verify" if res.kind == "substance" else "not_found"
        res.value = None
        res.candidates = list(candidates)
        res.reason = f"verifier rejected the model's answer: {why}"
        res.trace.append({"type": "verifier", "decision": "rejected", "why": why})
        return res

    def _tools(self, country):
        tools = {
            "eu_lookup": ({"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                          "Exact EU Pesticides Database lookup. Returns the EU record or null.", self._t_eu_lookup),
            "eu_search": ({"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]},
                          "List EU database substance names containing a keyword (max 15).", self._t_eu_search),
        }
        if country in (None, "MA"):
            tools["onssa_similar"] = ({"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                                      "Closest trade names in Morocco's ONSSA index.", self._t_onssa_similar)
        if self.search is not None:
            tools["web_search"] = ({"type": "object", "properties": {
                "query": {"type": "string"},
                "official_register_only": {"type": "boolean"}}, "required": ["query"]},
                "Web search (Tavily). Set official_register_only to restrict to the national register.", None)
            tools["web_extract"] = ({"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
                                    "Read one page returned by web_search (Tavily extract).", None)
        return tools

    def _t_eu_lookup(self, args, ctx):
        rec = self.eu.substance(args.get("name", ""))
        if not rec:
            return {"found": False}
        return {"found": True, "eu_name": rec["substance_name"], "status": rec["substance_status"],
                "residues": rec["pesticide_residues_linked"][:3]}

    def _t_eu_search(self, args, ctx):
        key = fold(args.get("keyword", ""))
        return {"names": [n for n in self._eu_names if key and key in fold(n)][:15]}

    def _t_onssa_similar(self, args, ctx):
        scored, prefix = self.fuzzy_products(args.get("name", ""), k=5)
        return {"closest": [{"name": n, "similarity": round(s, 2)} for s, n in scored], "starting_with": prefix[:5]}

    def _t_web_search(self, args, ctx):
        domains = OFFICIAL_DOMAINS.get(ctx["country"]) if args.get("official_register_only") and ctx["country"] else None
        hits = self.search.search(args.get("query", ""), include_domains=domains, max_results=5)
        for h in hits:
            ctx["seen"][h["url"]] = ctx["seen"].get(h["url"], "") + f"\n{h.get('title', '')}\n{h.get('content', '')}"
        return {"results": [{"url": h["url"], "title": h.get("title"), "snippet": (h.get("content") or "")[:600]} for h in hits]}

    def _t_web_extract(self, args, ctx):
        url = args.get("url", "")
        if url not in ctx["seen"]:
            return {"error": "only URLs returned by web_search can be read"}
        text = self.search.extract(url) or ""
        shown = text[:MAX_TOOL_TEXT]
        ctx["seen"][url] += "\n" + shown
        return {"url": url, "text": shown}

    def _run_agent(self, system, user, final_tool, country):
        tools = self._tools(country)
        handlers = {name: (h or getattr(self, f"_t_{name}")) for name, (_, _, h) in tools.items()}
        specs = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}} for n, (p, d, _) in tools.items()]
        specs.append({"type": "function", "function": final_tool})
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        ctx = {"seen": {}, "country": country}
        trace, cost, calls = [], 0.0, 0
        for step in range(self.max_steps):
            reply = self.model.chat(messages, specs)
            calls += 1
            cost += cost_usd(getattr(self.model, "model", ""), reply.get("usage", {}))
            trace.append({"type": "model", "step": step, "text": (reply.get("content") or "")[:300],
                          "tool_calls": [c["name"] for c in reply["tool_calls"]]})
            if not reply["tool_calls"]:
                messages.append({"role": "assistant", "content": reply.get("content") or ""})
                messages.append({"role": "user", "content": f"Call {final_tool['name']} to finish."})
                continue
            messages.append({"role": "assistant", "content": reply.get("content"), "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                for c in reply["tool_calls"]]})
            for c in reply["tool_calls"]:
                if c["name"] == final_tool["name"]:
                    trace.append({"type": "submit", "args": c["arguments"]})
                    return {"final": c["arguments"], "seen": ctx["seen"], "trace": trace, "cost": cost, "model_calls": calls,
                            "stop_reason": ""}
                handler = handlers.get(c["name"])
                try:
                    result = handler(c["arguments"], ctx) if handler else {"error": f"unknown tool {c['name']}"}
                except Exception as e:  # a failing tool must not crash the check; the model sees the error
                    result = {"error": str(e)[:200]}
                trace.append({"type": "tool", "name": c["name"], "args": c["arguments"], "result": _summary(result)})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, ensure_ascii=False)[:MAX_TOOL_TEXT]})
        return {"final": None, "seen": ctx["seen"], "trace": trace, "cost": cost, "model_calls": calls,
                "stop_reason": f"no answer within {self.max_steps} model steps"}


def _summary(result):
    if "results" in result:
        return {"urls": [r["url"] for r in result["results"]]}
    if "text" in result:
        return {"url": result.get("url"), "chars": len(result["text"])}
    return result


def _excerpt(text, needle, width=160):
    """Short excerpt around the needle, taken from the accent-folded text so offsets stay aligned."""
    f = fold(text)
    i = f.find(fold(needle))
    start = max(0, i - width // 2) if i >= 0 else 0
    return f[start:start + width]
