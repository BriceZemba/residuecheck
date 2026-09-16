"""Chat model clients for the agents.

TokenFactory  Nemotron on Nebius Token Factory (OpenAI-compatible API, NEBIUS_API_KEY)
Scripted      replays prepared replies; used by tests and for replay mode

Both return the same normalised reply:
  {"content": str | None, "tool_calls": [{"id", "name", "arguments": dict}], "usage": {"prompt_tokens", "completion_tokens"}}
"""
import json
import os

from residuecheck.search import MissingKey

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
# USD per 1M tokens (input, output). From a third-party model list, 2026-09-13; to be replaced by S1 results
# from GET /v1/models?verbose=true once billing works.
PRICES = {
    "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
    "nvidia/Nemotron-3_5-Lightning": (0.06, 0.24),
    "nvidia/Nemotron-3-Ultra-550b-a55b": (1.00, 3.00),
}


def cost_usd(model, usage):
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return (usage.get("prompt_tokens", 0) * p_in + usage.get("completion_tokens", 0) * p_out) / 1e6


class TokenFactory:
    def __init__(self, model=DEFAULT_MODEL, api_key=None, temperature=0.0, max_tokens=1200):
        key = api_key or os.environ.get("NEBIUS_API_KEY")
        if not key:
            raise MissingKey("NEBIUS_API_KEY is not set (Token Factory billing not active yet)")
        from openai import OpenAI

        self.client = OpenAI(base_url=BASE_URL, api_key=key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages, tools):
        r = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools, tool_choice="auto",
                                                temperature=self.temperature, max_tokens=self.max_tokens)
        msg = r.choices[0].message
        calls = []
        for c in msg.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable": c.function.arguments}
            calls.append({"id": c.id, "name": c.function.name, "arguments": args})
        usage = {"prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens} if r.usage else {}
        return {"content": msg.content, "tool_calls": calls, "usage": usage}


class Scripted:
    """Replays a list of replies in order. Each reply is either a tool call list or plain text."""

    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen_messages = []

    def chat(self, messages, tools):
        self.seen_messages.append([dict(m) for m in messages])
        if not self.replies:
            return {"content": "I have nothing more to add.", "tool_calls": [], "usage": {}}
        reply = self.replies.pop(0)
        if isinstance(reply, str):
            return {"content": reply, "tool_calls": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
        calls = [{"id": f"call_{len(self.seen_messages)}_{i}", "name": name, "arguments": args} for i, (name, args) in enumerate(reply)]
        return {"content": None, "tool_calls": calls, "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
