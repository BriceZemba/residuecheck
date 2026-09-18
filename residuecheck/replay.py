"""Record live model and web-search calls once; replay them later without any key.

Why: judges (and the hosted demo) must be able to use the agents without our Token Factory or Tavily keys, and
without spending credits. A recording is exact: every model reply and every Tavily result is stored under a hash of
the request that produced it. Everything else (EU snapshot, ONSSA cache, rules, verifier) runs live on replay, so a
replayed check goes through the same verifier as a live one.

A request that was not recorded raises ReplayMiss; callers fall back to the deterministic path and say so. If the
data the tools read changes, the requests change too and the replay misses instead of showing a stale answer.

Store: data/replays/<session>.json, one file per recording session, merged on load:
  {"session", "recorded_at", "model", "entries": [{"kind": "chat"|"search"|"extract", "key", "request", "reply"}]}
"""
import datetime
import hashlib
import json
import pathlib

REPLAYS = pathlib.Path(__file__).resolve().parents[1] / "data" / "replays"


class ReplayMiss(LookupError):
    pass


def request_key(kind, request):
    blob = json.dumps({"kind": kind, **request}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _chat_request(messages, tools):
    # Tool specs are part of the key: a changed tool description is a different request.
    return {"messages": messages, "tools": tools}


class Store:
    def __init__(self, folder=REPLAYS):
        self.folder = pathlib.Path(folder)
        self.entries, self.sessions = {}, []
        for path in sorted(self.folder.glob("*.json")) if self.folder.exists() else []:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.sessions.append({"session": data["session"], "recorded_at": data["recorded_at"],
                                  "model": data.get("model"), "entries": len(data["entries"]),
                                  "scenarios": data.get("scenarios", [])})
            for e in data["entries"]:
                self.entries[e["key"]] = e

    def __len__(self):
        return len(self.entries)

    @property
    def scenarios(self):
        return sorted({s for sess in self.sessions for s in sess["scenarios"]})

    def get(self, kind, request):
        e = self.entries.get(request_key(kind, request))
        if e is None:
            raise ReplayMiss(f"{kind} request not in the recording")
        return e["reply"]


class Session:
    """Collects entries during a live run and writes them as one session file."""

    def __init__(self, name, model_name=None, folder=REPLAYS):
        self.name, self.model_name, self.folder = name, model_name, pathlib.Path(folder)
        self.entries, self.scenarios = {}, []  # scenario ids recorded completely in this session

    def add(self, kind, request, reply):
        # Copy now: the agent loop keeps appending to the same message list after the call.
        request, reply = (json.loads(json.dumps(x, ensure_ascii=False, default=str)) for x in (request, reply))
        key = request_key(kind, request)
        self.entries[key] = {"kind": kind, "key": key, "request": request, "reply": reply}

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{self.name}.json"
        data = {"session": self.name, "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "model": self.model_name, "scenarios": sorted(self.scenarios),
                "entries": [self.entries[k] for k in sorted(self.entries)]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        return path


class RecordingModel:
    def __init__(self, model, session):
        self.inner, self.session = model, session
        self.model = getattr(model, "model", None)

    def chat(self, messages, tools):
        reply = self.inner.chat(messages, tools)
        self.session.add("chat", _chat_request(messages, tools), reply)
        return reply


class ReplayModel:
    def __init__(self, store, model_name=None):
        self.store = store
        self.model = model_name  # cost is looked up by name; replayed usage costs nothing new but is shown as recorded

    def chat(self, messages, tools):
        return self.store.get("chat", _chat_request(messages, tools))


class RecordingSearch:
    def __init__(self, search, session):
        self.inner, self.session = search, session
        self.name = f"recording:{getattr(search, 'name', 'search')}"

    def search(self, query, include_domains=None, max_results=5):
        hits = self.inner.search(query, include_domains=include_domains, max_results=max_results)
        self.session.add("search", {"query": query, "include_domains": include_domains, "max_results": max_results}, hits)
        return hits

    def extract(self, url, query=None):
        text = self.inner.extract(url, query=query)
        self.session.add("extract", {"url": url, "query": query}, text)
        return text


class ReplaySearch:
    name = "replay"

    def __init__(self, store):
        self.store = store

    def search(self, query, include_domains=None, max_results=5):
        return self.store.get("search", {"query": query, "include_domains": include_domains, "max_results": max_results})

    def extract(self, url, query=None):
        return self.store.get("extract", {"url": url, "query": query})
