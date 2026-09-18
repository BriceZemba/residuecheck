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


def test_g2b_and_g2s_sets():
    import importlib.util

    from residuecheck.eu_data import Snapshot

    eu = Snapshot("2026-09-13")
    g2b = load("g2b", "all")
    assert len(g2b) == 15 and sum(c["split"] == "heldout" for c in g2b) == 5
    for c in g2b:
        t = c["truth"]
        if t["status"] == "found":
            assert t["url"].startswith(("https://bku.tarimorman.gov.tr/", "http://www.apc.gov.eg/"))
            assert all(eu.substance(n)["substance_name"] == n for n in t["eu_substances"])
            assert "خام" not in c["question"]["trade_name"]  # technical grade excluded
    g2s = load("g2s", "all")
    assert len(g2s) == 33 and sum(c["split"] == "heldout" for c in g2s) == 10
    assert len({c["question"]["label_name"] for c in g2s}) == 33
    spec = importlib.util.spec_from_file_location("build_g2s", ROOT / "eval" / "build_g2s.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    before = (ROOT / "eval" / "heldout" / "g2s_heldout.jsonl").read_bytes()
    import tempfile, pathlib as _p
    with tempfile.TemporaryDirectory() as tmp:
        mod.OUT_DEV, mod.OUT_HELDOUT, mod.OUT_MANIFEST = (_p.Path(tmp) / n for n in ("d", "h", "m"))
        mod.main()
        assert (_p.Path(tmp) / "h").read_bytes() == before


def test_g2b_scoring():
    from run import score_g2b

    case = {"truth": {"status": "found", "trade_name": "AZOSTAR 320 SC", "eu_substances": ["Tebuconazole", "Azoxystrobin"]}}
    ok = score_g2b(case, {"status": "resolved", "trade_name": "Azostar 320 SC", "eu_substances": ["Azoxystrobin", "Tebuconazole"]})
    assert ok["pass"]
    wrong = score_g2b(case, {"status": "resolved", "trade_name": "AZOSTAR 250 SC", "eu_substances": ["Azoxystrobin"]})
    assert wrong["wrong_product"] and not wrong["pass"]
    asked = score_g2b(case, {"status": "suggested", "trade_name": "AZOSTAR 320 SC", "eu_substances": []})
    assert asked["abstained"] and not asked["pass"]
    fake = {"truth": {"status": "not_found"}}
    assert score_g2b(fake, {"status": "cannot_verify"})["pass"]
    assert not score_g2b(fake, {"status": "resolved", "trade_name": "X"})["pass"]


def test_g2s_no_eu_substance_requires_refusal():
    from residuecheck.eu_data import Snapshot
    from run import score_g2s

    eu = Snapshot("2026-09-13")
    case = {"truth": {"eu_substance": None, "expected": "no_eu_substance"}}
    assert score_g2s(case, {"status": "cannot_verify", "eu_substance": None}, eu)["pass"]
    invented = score_g2s(case, {"status": "resolved", "eu_substance": "Cloquintocet"}, eu)
    assert not invented["pass"] and invented["wrong"]


def test_g6_set_is_consistent():
    from residuecheck.alternatives import Alternatives, _load_record
    from residuecheck.eu_data import Snapshot

    eu = Snapshot("2026-09-13")
    alt = Alternatives(eu)
    cases = load("g6", "all")
    assert len(cases) == 19 and sum(c["split"] == "heldout" for c in cases) == 6
    for c in cases:
        q, t = c["question"], c["truth"]
        assert "MRL_AT_LOQ" in t["failing_codes"]
        assert q["failing_product"] not in t["safe_products"]
        assert set(t["latest_spray"]) == set(t["safe_products"])
        assert all(d >= q["not_before"] for d in t["latest_spray"].values())
        failing = {eu.substance(s["name_fr"])["substance_name"] if eu.substance(s["name_fr"]) else s["name_fr"]
                   for s in _load_record(q["failing_product"])["substances"]}
        for name in t["safe_products"][:5]:
            subs = {eu.substance(s["name_fr"])["substance_name"] for s in _load_record(name)["substances"]}
            assert not subs & failing
        assert alt.safe_set(q["failing_product"], q["crop_code"], q["harvest_on"], q["not_before"]) == t["safe_products"]


def test_g6_scoring():
    from run import score_g6

    case = {"truth": {"safe_products": ["CORAGEN", "OIKOS"], "latest_spray": {"CORAGEN": "2026-12-08", "OIKOS": "2026-12-12"},
                      "has_safe_option": True}}
    good = score_g6(case, {"shown": [{"product": "CORAGEN", "spray_on": "2026-12-01"}], "proposed": [
        {"product": "CORAGEN"}, {"product": "ACTARA 25 WG"}], "rejected": 1})
    assert good["pass"] and good["proposed_unsafe"] == 1 and good["shown_unsafe"] == 0
    late = score_g6(case, {"shown": [{"product": "CORAGEN", "spray_on": "2026-12-10"}], "proposed": [], "rejected": 0})
    assert not late["pass"] and late["shown_unsafe"] == 1
    empty = {"truth": {"safe_products": [], "latest_spray": {}, "has_safe_option": False}}
    assert score_g6(empty, {"shown": [], "proposed": [], "rejected": 0})["pass"]
    assert not score_g6(empty, {"shown": [{"product": "X", "spray_on": None}], "proposed": [], "rejected": 0})["pass"]


def test_g4_set_is_consistent():
    cases = load("g4", "all")
    manifest = json.loads((ROOT / "eval" / "gold" / "g4_manifest.json").read_text(encoding="utf-8"))
    assert len(cases) == manifest["total"] == 564
    assert sum(c["split"] == "heldout" for c in cases) == manifest["heldout"] == 169
    assert len({c["question"]["reference"] for c in cases}) == len(cases)
    labels = json.loads((ROOT / "eval" / "labels" / "g4_labels.json").read_text(encoding="utf-8"))
    for c in cases:
        q, t = c["question"], c["truth"]
        assert q["substances"] == [s["eu_substance"] for s in t["substances"]]
        assert set(t["unauthorised"]) <= set(q["substances"])
        expected = labels["by_reference"].get(q["reference"]) or labels["by_name"][q["product_as_notified"]]
        assert q["crop_code"] == expected
        statuses = {s["limit_status"] for s in t["substances"]}
        assert (c["stratum"] == "preventable") == bool(statuses & {"at_loq", "not_listed"})


def test_g4_scoring():
    from run import score_g4

    sub = lambda name, status, unauth=False: {"eu_substance": name, "limit_status": status, "rasff_unauthorised": unauth}  # noqa: E731
    case = {"stratum": "preventable", "truth": {"substances": [sub("A", "at_loq", True), sub("B", "above_loq")], "unauthorised": ["A"]}}
    good = score_g4(case, {"verdict": "RED", "levels": {"A": "RED", "B": "GREEN"}})
    assert good["pass"] and good["unauthorised_red"] == 1 and not good["substance_misses"]
    green = score_g4(case, {"verdict": "GREEN", "levels": {"A": "GREEN", "B": "GREEN"}})
    assert not green["pass"] and green["false_green"] and green["substance_misses"] == ["A"]
    # Blocked for the wrong substance: the lot passes, the missed substance is still counted.
    other = score_g4(case, {"verdict": "RED", "levels": {"A": "AMBER", "B": "RED"}})
    assert other["pass"] and other["substance_misses"] == ["A"] and other["unauthorised_not_green"] == 1
    dose = {"stratum": "dose_dependent", "truth": {"substances": [sub("B", "above_loq")], "unauthorised": []}}
    s = score_g4(dose, {"verdict": "GREEN", "levels": {"B": "GREEN"}})
    assert s["pass"] and s["silent_green"]
    unknown = {"stratum": "unknown_history", "truth": {"substances": [sub("C", "history_not_in_snapshot")], "unauthorised": []}}
    assert score_g4(unknown, {"verdict": "CANNOT_VERIFY", "levels": {"C": "CANNOT_VERIFY"}})["pass"]
    assert not score_g4(unknown, {"verdict": "GREEN", "levels": {"C": "GREEN"}})["pass"]
