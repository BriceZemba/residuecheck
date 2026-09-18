"""Which engine answers a check: live agents, replayed agents, or fixed rules only.

RESIDUECHECK_ENGINE
  auto    (default) live if NEBIUS_API_KEY is set, else replay if recordings exist, else rules
  live    Nemotron on Token Factory + Tavily; RESIDUECHECK_RECORD=<session> also records every call
  replay  recorded calls from data/replays (or RESIDUECHECK_REPLAY_DIR), no key used; unrecorded inputs fall back
          to fixed rules
  rules   no model at all

Live mode has a daily spend cap (RESIDUECHECK_DAILY_USD, default 2.00) so a public demo cannot drain the credits;
past the cap, checks run on fixed rules and say so.
"""
import datetime
import os
import threading

from residuecheck.replay import REPLAYS, RecordingModel, RecordingSearch, ReplayModel, ReplaySearch, Session, Store
from residuecheck.search import MissingKey, default_search

RULES_NOTE = ("No language model: products are matched by exact name (close names are suggested), verdicts and safer "
              "options come from fixed rules.")


class Engine:
    def __init__(self, mode, model=None, search=None, session=None, store=None, daily_usd=2.0, note=""):
        self.mode, self.model, self.search, self.session, self.store = mode, model, search, session, store
        self.daily_usd, self.note = daily_usd, note
        self._spent, self._day, self._lock = 0.0, datetime.date.today(), threading.Lock()

    @property
    def model_name(self):
        return getattr(self.model, "model", None)

    def info(self):
        out = {"name": {"live": "live agents", "replay": "recorded agents (replay)", "rules": "rules-only"}[self.mode],
               "mode": self.mode, "model": self.model_name, "note": self.note,
               "search": getattr(self.search, "name", None)}
        if self.store is not None:
            out["recordings"] = self.store.sessions
        return out

    def agent_allowed(self):
        """True when a model call may be made now (live budget not used up)."""
        if self.model is None:
            return False
        if self.mode != "live":
            return True
        with self._lock:
            if datetime.date.today() != self._day:
                self._day, self._spent = datetime.date.today(), 0.0
            return self._spent < self.daily_usd

    def spend(self, usd):
        with self._lock:
            if self.mode == "live":
                self._spent += usd or 0.0
            if self.session is not None:
                self.session.save()


def from_env(env=None, store=None):
    env = os.environ if env is None else env
    mode = env.get("RESIDUECHECK_ENGINE", "auto")
    daily = float(env.get("RESIDUECHECK_DAILY_USD", "2.0"))
    if mode in ("auto", "live") and env.get("NEBIUS_API_KEY"):
        from residuecheck.llm import TokenFactory

        model = TokenFactory(api_key=env["NEBIUS_API_KEY"])
        try:
            search = default_search()
        except MissingKey:
            search = None
        session = None
        if env.get("RESIDUECHECK_RECORD"):
            session = Session(env["RESIDUECHECK_RECORD"], model.model)
            model, search = RecordingModel(model, session), (RecordingSearch(search, session) if search else None)
        note = (f"Live: {model.model} on Nebius Token Factory"
                + (" with Tavily web search" if search else " (no web search configured)")
                + f"; daily spend capped at ${daily:.2f}, then fixed rules.")
        return Engine("live", model, search, session=session, daily_usd=daily, note=note)
    if mode == "live":
        raise MissingKey("RESIDUECHECK_ENGINE=live needs NEBIUS_API_KEY")
    if mode in ("auto", "replay"):
        store = store if store is not None else Store(env.get("RESIDUECHECK_REPLAY_DIR") or REPLAYS)
        if len(store):
            models = sorted({s["model"] for s in store.sessions if s.get("model")})
            dates = sorted(s["recorded_at"][:10] for s in store.sessions)
            note = (f"Replay: recorded {', '.join(models) or 'model'} and Tavily calls ({dates[0]} to {dates[-1]}) are "
                    "played back; no key is used and the verifier and rules run live. Inputs outside the recording are "
                    "checked by fixed rules only, and the result says so.")
            return Engine("replay", ReplayModel(store, models[0] if models else None), ReplaySearch(store),
                          store=store, note=note)
        if mode == "replay":
            return Engine("rules", note="Replay requested but no recordings found. " + RULES_NOTE, store=store)
    return Engine("rules", note=RULES_NOTE)
