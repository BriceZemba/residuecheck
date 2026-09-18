"""Spray-log photo -> rows the rules can check.

A vision model reads the photo and returns JSON. Its output is never used as is: `validate` keeps only fields that
are present and well-formed, forces flagged-unreadable fields to empty, and drops rows with nothing in them.
`usable_rows` then keeps rows the check can use (not crossed out, product and date both readable) and lists the
others for the grower to confirm. Nothing is guessed: an unreadable cell stays unreadable.

The vision model is configurable (RESIDUECHECK_VISION_MODEL) because the Token Factory vision line-up is only known
once spike S1 runs; without a key or a model name `vision_model()` raises MissingKey and the eval skips G3.
"""
import base64
import datetime
import json
import mimetypes
import os
import pathlib
import re

from residuecheck.search import MissingKey

FIELDS = ("date", "product", "dose", "target")
PROMPT = """You read a handwritten pesticide treatment log (cahier de traitements) from a farm.
Return only JSON, no prose:
{"crop": string or null,
 "rows": [{"date": "YYYY-MM-DD" or null, "product": string or null, "dose": string or null, "target": string or null,
           "crossed_out": true or false, "unreadable": [names of fields you cannot read]}],
 "notes": string}
Rules:
- One entry per written line, in page order. Include crossed-out lines with "crossed_out": true.
- Copy product names exactly as written (keep spelling and case); do not correct them.
- If a cell is hidden, smudged or illegible, set it to null and add its name to "unreadable". Never guess it.
- Dates: write them as YYYY-MM-DD. If the year is missing, use the season on the page and neighbouring lines.
- Do not add lines that are not on the page."""


def vision_model():
    name = os.environ.get("RESIDUECHECK_VISION_MODEL")
    if not name:
        raise MissingKey("RESIDUECHECK_VISION_MODEL is not set (vision model not chosen yet; spike S1)")
    from residuecheck.llm import TokenFactory

    return TokenFactory(model=name, max_tokens=2000)


def image_part(image):
    """A path or raw bytes -> OpenAI-style image content part (data URL)."""
    if isinstance(image, (str, pathlib.Path)):
        path = pathlib.Path(image)
        data, mime = path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/jpeg"
    else:
        data, mime = image, "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}


def extract_json(text):
    """The first JSON object in a reply (models sometimes wrap it in a code fence or add a sentence)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:text.rfind("}") + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def validate(raw):
    """Model JSON -> (parsed, problems). Never adds information; only removes or blanks what is not well-formed."""
    problems = []
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list):
        return {"crop": None, "rows": []}, ["reply is not a JSON object with a rows list"]
    rows = []
    for i, r in enumerate(raw["rows"], start=1):
        if not isinstance(r, dict):
            problems.append(f"line {i}: not an object, dropped")
            continue
        unreadable = sorted({f for f in (r.get("unreadable") or []) if f in FIELDS})
        row = {"date": _date(r.get("date")), "product": _text(r.get("product")), "dose": _text(r.get("dose")),
               "target": _text(r.get("target")), "crossed_out": r.get("crossed_out") is True, "unreadable": unreadable}
        if r.get("date") and row["date"] is None:
            problems.append(f"line {i}: date {r.get('date')!r} is not YYYY-MM-DD, marked unreadable")
            row["unreadable"] = sorted(set(unreadable) | {"date"})
        for f in row["unreadable"]:
            row[f] = None  # a field the model could not read keeps no value, whatever it wrote
        if not any(row[f] for f in FIELDS) and not row["unreadable"]:
            problems.append(f"line {i}: empty, dropped")
            continue
        rows.append(row)
    return {"crop": _text(raw.get("crop")), "rows": rows}, problems


def usable_rows(parsed):
    """Rows the check can run on, and rows the grower must confirm first (with the reason)."""
    usable, review = [], []
    for i, r in enumerate(parsed["rows"], start=1):
        if r["crossed_out"]:
            continue
        missing = [f for f in ("product", "date") if not r[f]]
        if missing:
            review.append({"line": i, "row": r, "reason": f"{' and '.join(missing)} unreadable, please type it in"})
        else:
            usable.append(r)
    return usable, review


class LogParser:
    def __init__(self, model):
        self.model = model

    def parse(self, image, crop_hint=None):
        text = PROMPT + (f"\nThe grower says the crop is: {crop_hint}." if crop_hint else "")
        messages = [{"role": "user", "content": [{"type": "text", "text": text}, image_part(image)]}]
        reply = self.model.chat(messages, [])
        raw = extract_json(reply.get("content"))
        parsed, problems = validate(raw)
        if raw is None:
            problems.insert(0, "no JSON in the model reply")
        from residuecheck.llm import cost_usd

        return {**parsed, "problems": problems, "model": getattr(self.model, "model", None),
                "cost_usd": cost_usd(getattr(self.model, "model", ""), reply.get("usage") or {})}
