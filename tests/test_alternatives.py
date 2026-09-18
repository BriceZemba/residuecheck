"""Safe-alternatives tests on real cached ONSSA records and the real EU snapshot, with a small injected crop index.

ACTARA 25 WG (thiamethoxam, leaf miner on citrus) is RED on oranges: its EU limit is at the limit of quantification.
Scripted replies stand in for Nemotron until Token Factory billing works.
"""
import datetime

import pytest

from residuecheck.alternatives import Alternatives
from residuecheck.eu_data import Snapshot
from residuecheck.llm import Scripted

ORANGES = "0110020"
HARVEST = "2026-12-15"
INDEX = {"Agrumes": {"products": ["ACTARA 25 WG", "ACETA", "CORAGEN", "AGRIMEC GOLD", "OIKOS", "ALKADOR",
                                  "ACRAMITE 480 SC", "ADMIRAL 10 EC", "ALFIL"]}}


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


def alt(eu, replies=None, **kw):
    return Alternatives(eu, index=INDEX, model=Scripted(replies) if replies is not None else None, **kw)


def test_failing_product_is_red(eu):
    a = alt(eu)
    from residuecheck.alternatives import _load_record
    verdict, reasons = a.check(_load_record("ACTARA 25 WG"), ORANGES, datetime.date(2026, 11, 1), datetime.date(2026, 12, 15))
    assert verdict.name == "RED" and reasons[0].startswith("MRL_AT_LOQ")


def test_deterministic_plan_offers_safe_same_pest_options(eu):
    plan = alt(eu).plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    names = [o.product for o in plan.options]
    assert plan.status == "deterministic" and 1 <= len(names) <= 3
    assert "ACTARA 25 WG" not in names
    assert not {"ALKADOR", "ACRAMITE 480 SC", "ADMIRAL 10 EC", "ALFIL"} & set(names)  # AMBER / other pests / unverifiable
    assert all(o.verdict == "GREEN" and o.spray_on <= o.latest_spray for o in plan.options)
    assert len({tuple(o.substances) for o in plan.options}) == len(plan.options)  # different active substances


def test_close_to_harvest_only_short_interval_products_remain(eu):
    safe = alt(eu).safe_set("ACTARA 25 WG", ORANGES, HARVEST, "2026-12-10")  # 5 days before harvest
    assert safe == ["OIKOS"]  # 3-day interval; CORAGEN needs 7, AGRIMEC GOLD 14, ACETA 30


def test_safe_set_matches_deterministic_acceptance(eu):
    a = alt(eu)
    safe = a.safe_set("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert safe == sorted(["ACETA", "AGRIMEC GOLD", "CORAGEN", "OIKOS"])


def test_agent_proposals_are_verified_one_by_one(eu):
    plan = alt(eu, [
        [("list_candidates", {"pest": "mineuse"})],
        [("check_option", {"product": "CORAGEN", "spray_on": "2026-11-20"}),
         ("check_option", {"product": "ALKADOR", "spray_on": "2026-11-20"})],
        [("submit_alternatives", {"options": [
            {"product": "CORAGEN", "spray_on": "2026-11-20", "why": "different mode of action, 7-day interval"},
            {"product": "ALKADOR", "spray_on": "2026-11-20"},
            {"product": "ACTARA 25 WG", "spray_on": "2026-11-20"},
            {"product": "SUPERMINEUSE 50 SC", "spray_on": "2026-11-20"},
        ]})],
    ]).plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert plan.status == "verified" and [o.product for o in plan.options] == ["CORAGEN"]
    reasons = {r["product"]: r["why"] for r in plan.rejected}
    assert reasons["ALKADOR"].startswith("rules verdict AMBER")
    assert reasons["ACTARA 25 WG"] == "this is the product that fails"
    assert reasons["SUPERMINEUSE 50 SC"] == "not a product name in the ONSSA index"
    assert sum(1 for s in plan.trace if s["type"] == "verifier") == 3
    tool_steps = [s for s in plan.trace if s["type"] == "tool"]
    assert tool_steps[0]["result"]["candidates"] >= 4


def test_spray_date_after_latest_allowed_is_rejected(eu):
    plan = alt(eu, [[("submit_alternatives", {"options": [{"product": "ACETA", "spray_on": "2026-12-01"}]})]]
               ).plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert plan.status == "none_verified"
    assert "latest spray date is 2026-11-15" in plan.rejected[0]["why"]


def test_other_pest_is_rejected(eu):
    plan = alt(eu, [[("submit_alternatives", {"options": [{"product": "ADMIRAL 10 EC", "spray_on": "2026-11-01"}]})]]
               ).plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert "not registered against the same pest" in plan.rejected[0]["why"]


def test_closed_book_gets_no_tools_and_is_still_verified(eu):
    a = alt(eu, [[("submit_alternatives", {"options": [{"product": "CONFIDOR 200 OD"}, {"product": "EVISECT S"}]})]],
            use_tools=False)
    plan = a.plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert plan.status == "none_verified" and not plan.options and len(plan.rejected) == 2
    assert [t["function"]["name"] for t in a.model.seen_tools[0]] == ["submit_alternatives"]
    assert "no tools" in a.model.seen_messages[0][0]["content"]


def test_no_verifier_ablation_lets_unsafe_options_through(eu):
    plan = alt(eu, [[("submit_alternatives", {"options": [{"product": "ALKADOR", "spray_on": "2026-11-01"}]})]],
               verify=False).plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert plan.status == "unverified" and plan.options[0].product == "ALKADOR"


def test_unknown_failing_product_cannot_be_planned(eu):
    assert alt(eu).plan("ZORBEX 300 SC", ORANGES, HARVEST, "2026-11-01").status == "cannot_plan"


def test_same_active_substance_under_another_brand_is_rejected(eu):
    index = {"Agrumes": {"products": INDEX["Agrumes"]["products"] + ["COLUMBUS"]}}
    a = Alternatives(eu, index=index, model=Scripted([[("submit_alternatives", {"options": [
        {"product": "COLUMBUS", "spray_on": "2026-11-01"}, {"product": "CORAGEN", "spray_on": "2026-11-01"}]})]]))
    plan = a.plan("ACETA", ORANGES, HARVEST, "2026-11-01")  # ACETA and COLUMBUS are both acetamiprid
    assert [o.product for o in plan.options] == ["CORAGEN"]
    assert plan.rejected == [{"product": "COLUMBUS", "spray_on": "2026-11-01",
                              "why": "contains the same active substance as the failing product"}]


def test_deterministic_plan_fields_are_in_the_right_places(eu):
    plan = alt(eu).plan("ACTARA 25 WG", ORANGES, HARVEST, "2026-11-01")
    assert plan.proposed == [] and plan.rejected == [] and plan.candidates_checked >= 5
