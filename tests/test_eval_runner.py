"""Scorer behaviour on hand-made answers, and data-quality checks on G1/G2 questions."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from run import load, score_g1, score_g2  # noqa: E402

G1_CASE = {"truth": {"eu_substance": "Thiamethoxam", "crop_code": "0110020", "mrl_mg_per_kg": 0.01, "at_loq": True,
                     "no_mrl_required": False, "verdict": "RED"}}
G2_CASE = {"truth": {"status": "found", "onssa_trade_name": "ACTARA 25 WG", "substances": [{"name_fr": "Thiamethoxam"}],
                     "registered_for_crop": True, "dar_days": 28}}


def g1_answer(**kw):
    base = {"eu_substance": "Thiamethoxam", "crop_code": "0110020", "mrl_mg_per_kg": 0.01, "at_loq": True,
            "no_mrl_required": False, "verdict": "RED"}
    return {**base, **kw}


def test_g1_correct_answer_passes():
    assert score_g1(G1_CASE, g1_answer())["pass"]


def test_g1_green_on_red_is_a_false_green_and_missed_red():
    s = score_g1(G1_CASE, g1_answer(verdict="GREEN"))
    assert not s["pass"] and s["false_green"] and s["missed_red"]


def test_g1_right_verdict_wrong_limit_fails():
    s = score_g1(G1_CASE, g1_answer(mrl_mg_per_kg=0.15, at_loq=False))
    assert s["verdict_ok"] and not s["mrl_ok"] and not s["pass"]


def test_g1_abstaining_on_answerable_case_is_over_abstain():
    s = score_g1(G1_CASE, g1_answer(verdict="CANNOT_VERIFY", eu_substance=None))
    assert s["over_abstain"] and not s["pass"]


def test_g1_unknown_substance_needs_abstention():
    case = {"truth": {"eu_substance": None, "crop_code": "0110020", "verdict": "CANNOT_VERIFY"}}
    assert score_g1(case, g1_answer(verdict="CANNOT_VERIFY", eu_substance=None))["pass"]
    assert not score_g1(case, g1_answer(verdict="GREEN", eu_substance="Something"))["pass"]


def g2_answer(**kw):
    base = {"status": "found", "trade_name": "ACTARA 25 WG", "substances_fr": ["Thiamethoxam"],
            "registered_for_crop": True, "dar_days": 28}
    return {**base, **kw}


def test_g2_correct_answer_passes():
    assert score_g2(G2_CASE, g2_answer())["pass"]


def test_g2_wrong_product_is_flagged():
    s = score_g2(G2_CASE, g2_answer(trade_name="ACTELLIC 50 EC"))
    assert s["wrong_product"] and not s["pass"]


def test_g2_wrong_interval_fails():
    s = score_g2(G2_CASE, g2_answer(dar_days=7))
    assert s["product_ok"] and not s["dar_ok"] and not s["pass"]


def test_g2_accepting_a_fake_name_fails():
    s = score_g2({"truth": {"status": "not_found"}}, g2_answer())
    assert s["false_accept"] and not s["pass"]


def test_question_texts_are_clean():
    """Builder defects found on 2026-09-14: HTML entities, comma fragments of synonyms, bracketed residue definitions."""
    for suite in ("g1", "g2"):
        for c in load(suite, "all"):
            text = " ".join(str(v) for v in c["question"].values())
            assert not re.search(r"&[a-z]+;|\[|elsewhere", text), (c["id"], text)


def test_g2_sizes_and_fake_names_unknown():
    cases = load("g2", "all")
    assert len(cases) == 60
    assert sum(c["split"] == "heldout" for c in cases) == 18
    names = {n.upper().replace(" ", "") for n in json.loads((ROOT / "data" / "onssa_products_2026-09-14.json")
                                                             .read_text(encoding="utf-8"))["products"]}
    for c in cases:
        if c["stratum"] == "fake":
            assert c["question"]["trade_name"].upper().replace(" ", "") not in names
        if c["stratum"] == "variant":
            assert c["truth"]["resolvable_by_exact_normalised_match"] is False


def test_g2s_scoring_at_residue_level():
    from residuecheck.eu_data import Snapshot
    from run import score_g2s

    eu = Snapshot("2026-09-13")
    copper = {"truth": {"eu_substance": "Bordeaux mixture", "accept_same_residue": True}}
    oxy = eu.substance("Copper oxychloride")
    assert score_g2s(copper, {"status": "resolved", "eu_substance": "Copper oxychloride",
                              "residue_ids": eu.residue_ids(oxy)}, eu)["pass"]  # same copper residue
    strict = {"truth": {"eu_substance": "Pyrethrins"}}
    wrong = score_g2s(strict, {"status": "resolved", "eu_substance": "Deltamethrin", "residue_ids": [1]}, eu)
    assert not wrong["pass"] and wrong["wrong"]
    family = {"truth": {"eu_substance": "Paraffin oil", "family": "Paraffin oil/(CAS"}}
    assert score_g2s(family, {"status": "needs_confirmation", "eu_substance": "Paraffin oil",
                              "candidates": ["Paraffin oil/(CAS 8042-47-5)"]}, eu)["pass"]
    abstain = score_g2s(strict, {"status": "cannot_verify", "eu_substance": None}, eu)
    assert abstain["abstained"] and not abstain["wrong"]


def test_g2_right_first_suggestion_is_tracked_separately():
    s = score_g2(G2_CASE, {"status": "suggested", "trade_name": None, "suggestions": ["ACTARA 25 WG"]})
    assert s["first_suggestion_ok"] and s["abstained"] and not s["pass"]
