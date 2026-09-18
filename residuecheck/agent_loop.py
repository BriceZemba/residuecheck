"""Tool-calling loop shared by the resolver and the alternatives agent.

The model sees tool results; the loop records every step in a trace and adds up the cost. It stops when the model
calls the final tool (whose arguments are returned unverified: each agent verifies them itself) or after max_steps.
"""
import json

from residuecheck.llm import cost_usd

MAX_TOOL_TEXT = 3000


def _summary(result):
    if not isinstance(result, dict):
        return result
    if "results" in result:
        return {"urls": [r.get("url") for r in result["results"]]}
    if "text" in result:
        return {"url": result.get("url"), "chars": len(result["text"])}
    if "candidates" in result:
        return {"candidates": len(result["candidates"])}
    return result


def run_tool_loop(model, system, user, tools, final_tool, ctx, max_steps):
    """tools: {name: (json_schema, description, handler(args, ctx))}; final_tool: OpenAI function spec dict."""
    specs = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}} for n, (p, d, _) in tools.items()]
    specs.append({"type": "function", "function": final_tool})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    trace, cost, calls = [], 0.0, 0
    for step in range(max_steps):
        reply = model.chat(messages, specs)
        calls += 1
        cost += cost_usd(getattr(model, "model", ""), reply.get("usage", {}))
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
                return {"final": c["arguments"], "trace": trace, "cost": cost, "model_calls": calls, "stop_reason": ""}
            entry = tools.get(c["name"])
            try:
                result = entry[2](c["arguments"], ctx) if entry else {"error": f"unknown tool {c['name']}"}
            except Exception as e:  # a failing tool must not crash the check; the model sees the error
                result = {"error": str(e)[:200]}
            trace.append({"type": "tool", "name": c["name"], "args": c["arguments"], "result": _summary(result)})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False, default=str)[:MAX_TOOL_TEXT]})
    return {"final": None, "trace": trace, "cost": cost, "model_calls": calls,
            "stop_reason": f"no answer within {max_steps} model steps"}
