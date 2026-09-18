"""Spray-log photo parsing: validation never adds information, and the G3 scorer catches the failures that matter.

Model replies are scripted: no vision model is wired yet (spike S1).
"""
import json
import pathlib
import sys

from residuecheck.llm import Scripted
from residuecheck.logparse import LogParser, extract_json, usable_rows, validate

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from run import load, score_g3  # noqa: E402


def test_validate_blanks_flagged_fields_and_bad_dates():
    parsed, problems = validate({"crop": "Agrumes", "rows": [
        {"date": "2026-09-01", "product": "ACTARA 25 WG", "dose": "20 g/hl", "target": "Mineuse", "unreadable": ["product"]},
        {"date": "01/09/26", "product": "CORAGEN", "dose": None, "target": None},
        {"date": None, "product": "  ", "dose": None, "target": None},
        "junk",
    ]})
    first, second = parsed["rows"]
    assert first["product"] is None and first["unreadable"] == ["product"]  # model wrote a value but flagged it
    assert second["date"] is None and "date" in second["unreadable"]
    assert len(problems) == 3


def test_validate_rejects_non_json_shapes():
    assert validate(None) == ({"crop": None, "rows": []}, ["reply is not a JSON object with a rows list"])
    assert extract_json('Here you go:\n```json\n{"rows": []}\n```') == {"rows": []}
    assert extract_json("no json here") is None


def test_usable_rows_skip_crossed_out_and_send_unreadable_to_review():
    parsed, _ = validate({"rows": [
        {"date": "2026-09-01", "product": "ACTARA 25 WG"},
        {"date": "2026-09-05", "product": "CORAGEN", "crossed_out": True},
        {"date": None, "product": "OIKOS", "unreadable": ["date"]},
    ]})
    usable, review = usable_rows(parsed)
    assert [r["product"] for r in usable] == ["ACTARA 25 WG"]
    assert review[0]["line"] == 3 and "date unreadable" in review[0]["reason"]


def test_parser_sends_the_image_and_validates_the_reply():
    reply = json.dumps({"crop": "Agrumes", "rows": [{"date": "2026-09-01", "product": "Blouz", "dose": "1 l/ha",
                                                     "target": "Ceratite", "crossed_out": False, "unreadable": []}]})
    model = Scripted([f"```json\n{reply}\n```"])
    out = LogParser(model).parse(ROOT / "eval" / "g3" / "log01.jpg", crop_hint="Agrumes")
    content = model.seen_messages[0][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "Never guess" in content[0]["text"] and "Agrumes" in content[0]["text"]
    assert model.seen_tools == [[]]
    assert out["rows"][0]["product"] == "Blouz" and out["problems"] == []


def oracle(case):
    """A perfect answer built from the truth (unreadable cells empty and flagged)."""
    rows = []
    for t in case["truth"]["rows"]:
        rows.append({"date": t["date"], "product": t["product_as_written"], "dose": t["dose"], "target": t["target"],
                     "crossed_out": t["crossed_out"], "unreadable": list(t["unreadable"])})
    return {"rows": rows, "resolved": [t["product"] for t in case["truth"]["rows"]]}


def test_g3_set_and_oracle():
    cases = load("g3", "all")
    assert len(cases) >= 6 and {c["split"] for c in cases} == {"dev", "heldout"}
    for c in cases:
        assert (ROOT / c["question"]["image"]).exists()
        s = score_g3(c, oracle(c))
        assert s["pass"] and s["fields_ok"] == s["fields_checked"] and s["resolved_ok"] == s["resolved_checked"], (c["id"], s)
    smudged = [t for c in cases for t in c["truth"]["rows"] if t["unreadable"]]
    assert smudged and all(t[f] is None and t["hidden"][f] for t in smudged for f in t["unreadable"])
    assert any(t["crossed_out"] for c in cases for t in c["truth"]["rows"])


def case_with(name):
    return next(c for c in load("g3", "all") if c["id"] == name)


def test_g3_guessing_a_smudged_cell_fails():
    c = case_with("g3-log05")
    a = oracle(c)
    row = next(i for i, t in enumerate(c["truth"]["rows"]) if "date" in t["unreadable"])
    a["rows"][row]["date"] = "2026-09-01"
    a["rows"][row]["unreadable"] = []
    s = score_g3(c, a)
    assert not s["pass"] and s["guessed_unreadable"] == 1


def test_g3_using_a_crossed_out_line_or_inventing_one_fails():
    c = case_with("g3-log04")
    a = oracle(c)
    crossed = next(i for i, t in enumerate(c["truth"]["rows"]) if t["crossed_out"])
    a["rows"][crossed]["crossed_out"] = False
    s = score_g3(c, a)
    assert not s["pass"] and s["crossed_used"] == 1
    b = oracle(c)
    b["rows"].append({"date": "2026-11-30", "product": "MOVENTO", "dose": "50 cc/hl", "target": "Pucerons",
                      "crossed_out": False, "unreadable": []})
    b["resolved"].append("MOVENTO")
    assert score_g3(c, b)["extra_rows"] == 1 and not score_g3(c, b)["pass"]
    # Leaving the crossed-out line out entirely is fine.
    d = oracle(c)
    del d["rows"][crossed], d["resolved"][crossed]
    assert score_g3(c, d)["pass"]


def test_g3_intended_product_counts_and_missed_rows_fail():
    c = case_with("g3-log02")
    a = oracle(c)
    row = next(i for i, t in enumerate(c["truth"]["rows"]) if t["product_as_written"] == "ACTRA 25 WG")
    a["rows"][row]["product"] = "ACTARA 25 WG"  # corrected spelling is accepted as the intended product
    assert score_g3(c, a)["pass"]
    a["resolved"][row] = "ACTARA 20 SC"
    assert score_g3(c, a)["resolved_wrong"] == 1
    del a["rows"][0], a["resolved"][0]
    s = score_g3(c, a)
    assert not s["pass"] and s["rows_found"] == s["rows_expected"] - 1
