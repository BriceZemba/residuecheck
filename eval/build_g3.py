"""Build eval set G3 (spray-log photos): handwritten treatment logs -> rows a check can use.

SYNTHETIC: the six images are rendered with handwriting-style fonts on simulated paper, and each carries a visible
"synthetic test image" note. They exercise layout, defects and honesty (unreadable cells must be flagged, crossed-out
entries must not be used); they are not a substitute for real photos, which go in eval/g3_real/ (see its README) and
are scored the same way as stratum "real".

Content is realistic: products are real ONSSA products registered for citrus, with the dose and target pest from
their own ONSSA label (cache of 2026-09-16). Farm and operator names are not written. Some product names are written
the way people write them (lower case, missing space, one misspelling); truth keeps both the text as written and the
intended ONSSA product.

Defects per image:
  log01  none (clean baseline), ruled paper
  log02  page tilted 4 degrees, one misspelled product
  log03  cursive font, blur and JPEG compression
  log04  one entry crossed out and rewritten on the next line
  log05  ink smudge over one date and over one product name (both must come back unreadable)
  log06  tilt, shadow, low contrast, mixed date formats, a smudged dose and a crossed-out entry

Truth per image (eval/g3/logNN.json): crop, rows[{n, date, date_as_written, product_as_written, product, dose,
target, crossed_out, unreadable}] where unreadable lists the fields hidden by a smudge (their values are kept under
hidden for reference only). Needs Windows handwriting fonts (C:/Windows/Fonts); the rendered images are committed.

Usage: python eval/build_g3.py
"""
import datetime
import json
import math
import pathlib
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from residuecheck.alternatives import _load_record  # noqa: E402

SEED = 20260919
FONTS = pathlib.Path("C:/Windows/Fonts")
OUT = ROOT / "eval" / "g3"
HELDOUT = {"log05", "log06"}  # 2 of 6 held out
OUT_DEV = ROOT / "eval" / "gold" / "g3_dev.jsonl"
OUT_HELDOUT = ROOT / "eval" / "heldout" / "g3_heldout.jsonl"
W, H = 1600, 1150
COLS = {"date": 90, "product": 330, "dose": 820, "target": 1080}
ROW0, ROW_H = 300, 92
SKIP_TARGETS = ("Adventices", "Action sur")  # herbicides and growth regulators are not sprayed on the canopy log
MAX_DOSE_CHARS, MAX_TARGET_CHARS = 14, 26  # longer label texts do not fit the column (traps, brushing mixes)

LOGS = [
    {"id": "log01", "font": "Inkfree.ttf", "size": 34, "rows": 6, "defects": []},
    {"id": "log02", "font": "segoepr.ttf", "size": 30, "rows": 7, "defects": ["tilt"], "tilt": 4.0,
     "misspell": {2: "ACTRA 25 WG"}, "force": {2: "ACTARA 25 WG"}},
    {"id": "log03", "font": "segoesc.ttf", "size": 29, "rows": 6, "defects": ["cursive", "blur", "jpeg"]},
    {"id": "log04", "font": "Inkfree.ttf", "size": 33, "rows": 7, "defects": ["crossed_out"], "cross": 3},
    {"id": "log05", "font": "BRADHITC.TTF", "size": 34, "rows": 6, "defects": ["smudge"],
     "smudge": [(1, "date"), (4, "product")]},
    {"id": "log06", "font": "LHANDW.TTF", "size": 26, "rows": 7, "defects": ["tilt", "shadow", "low_contrast", "mixed_dates",
     "smudge", "crossed_out"], "tilt": -3.0, "smudge": [(5, "dose")], "cross": 2, "mixed_dates": True},
]


def product_pool():
    index = json.loads((ROOT / "data" / "onssa_crops_index.json").read_text(encoding="utf-8"))
    pool = []
    for name in index["Agrumes"]["products"]:
        rec = _load_record(name)
        if not rec or not name.isascii():
            continue
        use = next((u for u in rec["usages"] if u["crop_fr"].startswith("Agrumes") and u.get("dose")), None)
        if not use or use["pest_fr"].startswith(SKIP_TARGETS):
            continue
        dose, target = use["dose"].strip(), use["pest_fr"].split("(")[0].strip()
        if len(dose) <= MAX_DOSE_CHARS and len(target) <= MAX_TARGET_CHARS and "piège" not in dose:
            pool.append({"product": rec["trade_name"], "dose": dose, "target": target})
    return pool


def as_written(name, rng):
    roll = rng.random()
    if roll < 0.35:
        return name.title()
    if roll < 0.5:
        return name.replace(" ", "", 1)
    return name


def written_date(day, rng, mixed):
    if mixed and rng.random() < 0.5:
        return rng.choice([f"{day.day}-{day.month}-{day.year % 100}", f"{day.day}/{day.month}"])
    return day.strftime("%d/%m/%y")


def paper(rng, ruled=True, contrast=1.0):
    img = Image.new("RGB", (W, H), (246, 243, 232))
    size = (W // 4, H // 4)
    noise = Image.frombytes("L", size, bytes(rng.randint(108, 148) for _ in range(size[0] * size[1])))
    noise = noise.resize((W, H)).convert("RGB")  # seeded, unlike Image.effect_noise
    img = Image.blend(img, noise, 0.05)
    d = ImageDraw.Draw(img)
    if ruled:
        for y in range(ROW0 - ROW_H + 60, H - 40, ROW_H // 2):
            d.line([(40, y), (W - 40, y)], fill=(185, 205, 230), width=2)
        d.line([(70, 40), (70, H - 40)], fill=(230, 160, 160), width=2)
    return img


def scribble(d, xy, text, font, rng, ink):
    """Draw text one character at a time with a wandering baseline."""
    x, y = xy
    drift = 0.0
    for ch in text:
        drift = max(-4.0, min(4.0, drift + rng.uniform(-0.8, 0.8)))
        d.text((x, y + drift), ch, font=font, fill=ink)
        x += font.getlength(ch) * rng.uniform(0.97, 1.05)
    return x


def smudge(img, box, rng):
    blot = Image.new("L", img.size, 0)
    b = ImageDraw.Draw(blot)
    x0, y0, x1, y1 = box
    b.rounded_rectangle([x0 - 6, y0 + 4, x1 + 6, y1 - 4], radius=18, fill=255)  # solid core: nothing stays legible
    for _ in range(14):
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        rx, ry = rng.uniform(25, 60), rng.uniform(14, 30)
        b.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    blot = blot.filter(ImageFilter.GaussianBlur(6))
    ink = Image.new("RGB", img.size, (38, 44, 78))
    return Image.composite(ink, img, blot.point(lambda v: min(255, int(v * 1.1))))


def render(spec, rows, rng):
    img = paper(rng)
    d = ImageDraw.Draw(img)
    hand = ImageFont.truetype(str(FONTS / spec["font"]), spec["size"])
    head = ImageFont.truetype(str(FONTS / spec["font"]), spec["size"] + 6)
    printed = ImageFont.truetype(str(FONTS / "arial.ttf"), 22)
    ink = (28, 40, 110) if "low_contrast" not in spec["defects"] else (95, 110, 150)
    d.text((140, H - 90), "SYNTHETIC TEST IMAGE - ResidueCheck eval G3", font=printed, fill=(150, 150, 150))
    scribble(d, (100, 70), "Cahier de traitements - Agrumes (oranger)", head, rng, ink)
    scribble(d, (100, 140), "Parcelle P3   Campagne 2026/27", hand, rng, ink)
    for key, label in (("date", "Date"), ("product", "Produit"), ("dose", "Dose"), ("target", "Cible")):
        scribble(d, (COLS[key], ROW0 - 70), label, head, rng, ink)
    smudges = []
    for i, r in enumerate(rows):
        y = ROW0 + i * ROW_H + rng.randint(-4, 4)
        ends = {}
        for key, text in (("date", r["date_as_written"]), ("product", r["product_as_written"]),
                          ("dose", r["dose"]), ("target", r["target"])):
            ends[key] = scribble(d, (COLS[key] + rng.randint(-6, 6), y), text, hand, rng, ink)
            if key in r["unreadable"]:
                smudges.append((COLS[key] - 12, y - 8, ends[key] + 10, y + spec["size"] + 12))
        if r["crossed_out"]:
            pts = [(COLS["date"] - 10 + k * 30, y + spec["size"] * 0.55 + 6 * math.sin(k)) for k in range(int((ends["target"] - 60) / 30))]
            d.line(pts, fill=ink, width=4)
    for box in smudges:
        img = smudge(img, box, rng)
    if "shadow" in spec["defects"]:
        grad = Image.linear_gradient("L").rotate(90).resize(img.size).point(lambda v: 150 + v * 105 // 255)
        img = Image.composite(img, Image.new("RGB", img.size, (0, 0, 0)), grad)
    if spec.get("tilt"):
        img = img.rotate(spec["tilt"], resample=Image.BICUBIC, fillcolor=(90, 84, 76))
    if "blur" in spec["defects"]:
        img = img.filter(ImageFilter.GaussianBlur(1.6))
    return img


def build_rows(spec, pool, rng):
    count = spec["rows"]
    picks = rng.sample(pool, count + 1)
    for n, name in spec.get("force", {}).items():
        picks[n - 1] = next(p for p in pool if p["product"] == name)
    day = datetime.date(2026, 9, 1) + datetime.timedelta(rng.randint(0, 6))
    rows = []
    n = 0
    for i in range(count):
        n += 1
        p = picks[i]
        written = spec.get("misspell", {}).get(i + 1) or as_written(p["product"], rng)
        row = {"n": n, "date": day.isoformat(), "date_as_written": written_date(day, rng, spec.get("mixed_dates")),
               "product_as_written": written, "product": p["product"], "dose": p["dose"], "target": p["target"],
               "crossed_out": False, "unreadable": []}
        rows.append(row)
        if spec.get("cross") == i + 1:
            # Written, crossed out, then the right product on the next line (same day).
            row["crossed_out"] = True
            n += 1
            q = picks[count]
            rows.append({**row, "n": n, "product_as_written": as_written(q["product"], rng), "product": q["product"],
                         "dose": q["dose"], "target": q["target"], "crossed_out": False, "unreadable": []})
        day += datetime.timedelta(rng.randint(5, 16))
    for n_row, field in spec.get("smudge", []):
        rows[n_row - 1]["unreadable"].append(field)
    return rows


def main():
    rng = random.Random(SEED)
    pool = product_pool()
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for spec in LOGS:
        rows = build_rows(spec, pool, rng)
        img = render(spec, rows, rng)
        path = OUT / f"{spec['id']}.jpg"
        img.save(path, quality=62 if "jpeg" in spec["defects"] else 88)
        truth_rows = []
        for r in rows:
            hidden = {f: r[f] for f in r["unreadable"]}
            shown = {k: (None if k in r["unreadable"] else v) for k, v in r.items()}
            if "date" in r["unreadable"]:
                shown["date_as_written"] = None
            if "product" in r["unreadable"]:
                shown["product_as_written"] = None
            truth_rows.append({**shown, "hidden": hidden})
        truth = {"image": f"eval/g3/{spec['id']}.jpg", "synthetic": True, "font": spec["font"], "defects": spec["defects"],
                 "crop": "Agrumes", "crop_code": "0110020", "rows": truth_rows}
        (OUT / f"{spec['id']}.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        cases.append({"id": f"g3-{spec['id']}", "split": "heldout" if spec["id"] in HELDOUT else "dev",
                      "stratum": "synthetic", "question": {"image": truth["image"], "crop_hint": "Agrumes"}, "truth": truth})
    real = ROOT / "eval" / "g3_real"
    for tpath in sorted(real.glob("*.json")) if real.exists() else []:
        truth = json.loads(tpath.read_text(encoding="utf-8"))
        cases.append({"id": f"g3-real-{tpath.stem}", "split": truth.get("split", "dev"), "stratum": "real",
                      "question": {"image": truth["image"], "crop_hint": truth.get("crop")}, "truth": truth})
    for split, path in (("dev", OUT_DEV), ("heldout", OUT_HELDOUT)):
        path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases if c["split"] == split),
                        encoding="utf-8", newline="\n")
    summary = {c["id"]: {"split": c["split"], "rows": len(c["truth"]["rows"]), "defects": c["truth"].get("defects")} for c in cases}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
