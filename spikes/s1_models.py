"""Spike S1: which models does Token Factory serve, at what price, and can they do our steps?

Checks, in order:
  1. GET /v1/models?verbose=true -> every model with modality, context, prices.
  2. Function calling on NVIDIA text models (does the model emit a well-formed tool call?).
  3. JSON output on the cheapest NVIDIA model (row normalisation step).
  4. Vision: parse a synthetic spray-log image with every image-capable model (NVIDIA first),
     scored field by field against the known rows.

Writes spikes/results/s1-models.md (committed) and s1-models.raw.json (ignored).
The test image is synthetic (script-font text, not real handwriting); real handwritten logs are eval set G3.

Usage:
  set NEBIUS_API_KEY (or put it in ../.env), then: python spikes/s1_models.py
"""
import base64
import io
import json
import os
import pathlib
import time

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "results"
BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

# Known rows drawn into the test image. Product names are generic formulation names, not trademarks.
SPRAY_ROWS = [
    {"date": "02/03/2026", "product": "Chlorpyrifos 480 EC", "dose": "1.5 L/ha", "crop": "Orange"},
    {"date": "18/03/2026", "product": "Abamectin 18 EC", "dose": "0.5 L/ha", "crop": "Orange"},
    {"date": "05/04/2026", "product": "Copper hydroxide 50 WP", "dose": "3 kg/ha", "crop": "Orange"},
    {"date": "21/04/2026", "product": "Imidacloprid 200 SL", "dose": "0.75 L/ha", "crop": "Orange"},
]

MRL_TOOL = {
    "type": "function",
    "function": {
        "name": "eu_mrl_lookup",
        "description": "Look up the current EU maximum residue level for one active substance on one crop.",
        "parameters": {
            "type": "object",
            "properties": {
                "substance": {"type": "string", "description": "Active substance name, English, e.g. 'abamectin'"},
                "crop": {"type": "string", "description": "Crop name, English, e.g. 'oranges'"},
            },
            "required": ["substance", "crop"],
        },
    },
}


def load_key():
    key = os.environ.get("NEBIUS_API_KEY")
    env = ROOT.parent / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("NEBIUS_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("NEBIUS_API_KEY not set (env var or residuecheck/.env)")
    return key


def price(model, usage):
    p = model.get("pricing") or {}
    if not usage:
        return None
    return usage.prompt_tokens * float(p.get("prompt", 0)) + usage.completion_tokens * float(p.get("completion", 0))


def is_image_model(m):
    modality = (m.get("architecture") or {}).get("modality", "")
    return "image" in modality.split("->")[0]


def draw_spray_log():
    font_path = "C:/Windows/Fonts/segoesc.ttf"
    font = ImageFont.truetype(font_path, 30) if os.path.exists(font_path) else ImageFont.load_default()
    head = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 26) if os.path.exists("C:/Windows/Fonts/arial.ttf") else font
    img = Image.new("RGB", (1400, 520), (250, 248, 240))
    d = ImageDraw.Draw(img)
    cols = [40, 280, 780, 1060]
    d.text((40, 20), "Carnet de traitements - Parcelle B3", font=head, fill=(20, 20, 20))
    for x, h in zip(cols, ["Date", "Produit", "Dose", "Culture"]):
        d.text((x, 90), h, font=head, fill=(20, 20, 20))
    d.line((30, 130, 1370, 130), fill=(60, 60, 60), width=2)
    y = 150
    for r in SPRAY_ROWS:
        for x, k in zip(cols, ["date", "product", "dose", "crop"]):
            d.text((x, y), r[k], font=font, fill=(25, 40, 110))
        d.line((30, y + 70, 1370, y + 70), fill=(190, 190, 190), width=1)
        y += 85
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    (OUT / "s1-spray-log.png").write_bytes(buf.getvalue())
    return base64.b64encode(buf.getvalue()).decode()


def norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def score_rows(parsed):
    fields = ["date", "product", "dose", "crop"]
    total = len(SPRAY_ROWS) * len(fields)
    hit = 0
    for truth, got in zip(SPRAY_ROWS, parsed or []):
        for f in fields:
            if isinstance(got, dict) and norm(got.get(f, "")) == norm(truth[f]):
                hit += 1
    return hit, total


def extract_json(text):
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


def main():
    OUT.mkdir(exist_ok=True)
    client = OpenAI(base_url=BASE_URL, api_key=load_key())
    report = ["# Spike S1 results: Token Factory models", "", f"Run: {time.strftime('%Y-%m-%d %H:%M')} (local time)", ""]
    raw = {}

    # 1. Model catalogue
    models = client.get("/models", cast_to=object, options={"params": {"verbose": "true"}})["data"]
    raw["models"] = models
    nvidia = [m for m in models if m["id"].lower().startswith("nvidia/")]
    vision = sorted([m for m in models if is_image_model(m)], key=lambda m: not m["id"].lower().startswith("nvidia/"))

    report += ["## 1. Catalogue", "", f"{len(models)} models listed; {len(nvidia)} NVIDIA; {len(vision)} accept images.", "",
               "| Model | Modality | Context | $ / 1M in | $ / 1M out |", "|---|---|---|---|---|"]
    for m in sorted(models, key=lambda m: (not m["id"].lower().startswith("nvidia/"), m["id"])):
        p = m.get("pricing") or {}
        report.append(f"| `{m['id']}` | {(m.get('architecture') or {}).get('modality', '?')} | {m.get('context_length', '?')} "
                      f"| {float(p.get('prompt', 0)) * 1e6:.3f} | {float(p.get('completion', 0)) * 1e6:.3f} |")
    report.append("")

    # 2. Function calling on NVIDIA text models
    report += ["## 2. Function calling (NVIDIA text models)", "",
               "Prompt: can oranges treated with abamectin and imidacloprid be exported to the EU? Expect two `eu_mrl_lookup` calls.", "",
               "| Model | Tool calls | Args well-formed | Latency s | Cost $ |", "|---|---|---|---|---|"]
    raw["tools"] = {}
    for m in [m for m in nvidia if not is_image_model(m)]:
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=m["id"], tools=[MRL_TOOL], tool_choice="auto", max_tokens=800,
                messages=[{"role": "user", "content": "Can oranges treated with abamectin and imidacloprid be exported to the EU? Look up the limits first."}],
            )
            calls = r.choices[0].message.tool_calls or []
            ok = all({"substance", "crop"} <= set(json.loads(c.function.arguments)) for c in calls) if calls else False
            raw["tools"][m["id"]] = [c.function.arguments for c in calls]
            report.append(f"| `{m['id']}` | {len(calls)} | {ok} | {time.time() - t0:.1f} | {price(m, r.usage) or 0:.6f} |")
        except Exception as e:
            report.append(f"| `{m['id']}` | error | `{str(e)[:80]}` | {time.time() - t0:.1f} | |")
    report.append("")

    # 3. JSON output on cheapest NVIDIA text model
    text_nv = [m for m in nvidia if not is_image_model(m)]
    if text_nv:
        cheap = min(text_nv, key=lambda m: float((m.get("pricing") or {}).get("prompt", 1)))
        messy = "02/03 chlorpyriphos 480ec 1,5l/ha oranger ; 18-3 abamectine 18 EC 0.5 L oranges"
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=cheap["id"], max_tokens=600, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": "Normalise these spray records to JSON {\"rows\":[{date:DD/MM/2026, substance (English INN), dose, crop (English)}]}: " + messy}],
            )
            content = r.choices[0].message.content
            raw["json"] = content
            valid = True
            try:
                json.loads(content)
            except Exception:
                valid = False
            report += ["## 3. JSON normalisation (cheapest NVIDIA model)", "", f"Model `{cheap['id']}`, valid JSON: {valid}, "
                       f"latency {time.time() - t0:.1f} s, cost ${price(cheap, r.usage) or 0:.6f}", "", "```json", content[:800], "```", ""]
        except Exception as e:
            report += ["## 3. JSON normalisation", "", f"Error: `{str(e)[:200]}`", ""]

    # 4. Vision
    img_b64 = draw_spray_log()
    report += ["## 4. Vision parsing (synthetic script-font log, 4 rows x 4 fields)", "",
               "| Model | NVIDIA | Fields correct | Latency s | Cost $ |", "|---|---|---|---|---|"]
    raw["vision"] = {}
    for m in vision[:4]:
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=m["id"], max_tokens=800,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Transcribe every row of this spray log as a JSON array of objects with keys date, product, dose, crop. Copy text exactly; use null for unreadable cells. JSON only."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ]}],
            )
            content = r.choices[0].message.content
            raw["vision"][m["id"]] = content
            try:
                hit, total = score_rows(extract_json(content))
                score = f"{hit}/{total}"
            except Exception:
                score = "unparseable"
            report.append(f"| `{m['id']}` | {m['id'].lower().startswith('nvidia/')} | {score} | {time.time() - t0:.1f} | {price(m, r.usage) or 0:.6f} |")
        except Exception as e:
            report.append(f"| `{m['id']}` | {m['id'].lower().startswith('nvidia/')} | error `{str(e)[:60]}` | {time.time() - t0:.1f} | |")
    if not vision:
        report.append("| none | | no image-capable model listed | | |")
    report += ["", "## Decision", "", "[FILL after reading: vision model for step 1, text models for orchestration and cheap steps, prices to put in COMPETITION.md]", ""]

    (OUT / "s1-models.md").write_text("\n".join(report), encoding="utf-8")
    (OUT / "s1-models.raw.json").write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
