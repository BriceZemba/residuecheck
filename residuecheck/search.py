"""Web search and extraction for the resolver.

TavilyAPI    production path (tavily-python, TAVILY_API_KEY)
TavilyCLI    local development path (Tavily CLI with browser login), used while no API key is configured
FakeSearch   deterministic stand-in for tests

Every client returns plain dicts: search -> [{url, title, content, score}], extract -> text or None.
The resolver keeps the exact text it showed the model; verification never re-fetches a page.
"""
import json
import os
import shutil
import subprocess


class MissingKey(RuntimeError):
    pass


def _clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " …"


class TavilyAPI:
    name = "tavily-api"

    def __init__(self, api_key=None, search_depth="basic"):
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise MissingKey("TAVILY_API_KEY is not set")
        from tavily import TavilyClient

        self.client = TavilyClient(api_key=key)
        self.search_depth = search_depth
        self.calls = {"search": 0, "extract": 0}

    def search(self, query, include_domains=None, max_results=5):
        self.calls["search"] += 1
        body = self.client.search(query=query[:400], search_depth=self.search_depth, max_results=max_results,
                                  include_domains=list(include_domains) if include_domains else None)
        return [{"url": r["url"], "title": r.get("title", ""), "content": r.get("content", ""), "score": r.get("score")}
                for r in body.get("results", [])]

    def extract(self, url, query=None):
        self.calls["extract"] += 1
        body = self.client.extract(urls=[url], query=query, chunks_per_source=3 if query else None, format="markdown")
        results = body.get("results", [])
        return results[0].get("raw_content") if results else None


class TavilyCLI:
    """Development fallback: shells out to `tvly` (authenticated with `tvly login`)."""

    name = "tavily-cli"

    def __init__(self, exe=None):
        self.exe = exe or shutil.which("tvly")
        if not self.exe:
            raise MissingKey("Tavily CLI (tvly) not found")
        self.calls = {"search": 0, "extract": 0}

    def _run(self, args):
        proc = subprocess.run([self.exe, *args, "--json"], capture_output=True, text=True, encoding="utf-8", timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"tvly failed: {proc.stderr.strip()[:200]}")
        return json.loads(proc.stdout)

    def search(self, query, include_domains=None, max_results=5):
        self.calls["search"] += 1
        args = ["search", query[:400], "--max-results", str(max_results)]
        if include_domains:
            args += ["--include-domains", ",".join(include_domains)]
        body = self._run(args)
        return [{"url": r["url"], "title": r.get("title", ""), "content": r.get("content", ""), "score": r.get("score")}
                for r in body.get("results", [])]

    def extract(self, url, query=None):
        self.calls["extract"] += 1
        args = ["extract", url] + (["--query", query] if query else [])
        results = self._run(args).get("results", [])
        return results[0].get("raw_content") if results else None


class FakeSearch:
    """Test double. `pages` maps url -> (title, text); a search returns pages whose title or text contains any query word."""

    name = "fake"

    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = {"search": 0, "extract": 0}
        self.queries = []

    def search(self, query, include_domains=None, max_results=5):
        self.calls["search"] += 1
        self.queries.append(query)
        words = [w.lower() for w in query.split() if len(w) > 3]
        hits = []
        for url, (title, text) in self.pages.items():
            if include_domains and not any(d in url for d in include_domains):
                continue
            blob = f"{title} {text}".lower()
            if any(w in blob for w in words):
                hits.append({"url": url, "title": title, "content": _clip(text, 500), "score": 0.5})
        return hits[:max_results]

    def extract(self, url, query=None):
        self.calls["extract"] += 1
        page = self.pages.get(url)
        return page[1] if page else None


def default_search():
    """Tavily API if a key is configured, else the CLI; raises MissingKey if neither is available."""
    try:
        return TavilyAPI()
    except MissingKey:
        return TavilyCLI()
