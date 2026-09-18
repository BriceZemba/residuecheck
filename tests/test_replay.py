"""Replay mode: a recorded agent run plays back without keys, through the same verifier, and misses are explicit.

The "live" model here is a scripted one (Token Factory billing is not active yet); recording and replay do not care
what produced the replies.
"""
import pytest
from fastapi.testclient import TestClient

from residuecheck import api
from residuecheck.engine import RULES_NOTE, Engine, from_env
from residuecheck.eu_data import Snapshot
from residuecheck.llm import Scripted
from residuecheck.onssa import DATA, Onssa
from residuecheck.replay import (RecordingModel, RecordingSearch, ReplayMiss, ReplayModel, ReplaySearch, Session,
                                 Store)
from residuecheck.resolver import Resolver
from residuecheck.search import FakeSearch, MissingKey

APC = "http://www.apc.gov.eg/ar/PesticideDetails.aspx?id=11719"
PAGES = {APC: ("بيانات مبيد", "الإسم التجاري اب جريد 46% SL المواد الفعالة Bentazone + MCPA التركيز 40 + 6 الموقف من التسجيل مسجل")}
EG_RUN = [
    [("web_search", {"query": "اب جريد 46% SL", "official_register_only": True})],
    [("web_extract", {"url": APC})],
    [("submit_product", {"trade_name": "اب جريد 46% SL", "active_substances": ["Bentazone", "MCPA"], "evidence_url": APC})],
]
MA_INPUT = "Aktara thiametoxam"
MA_RUN = [
    [("onssa_similar", {"name": MA_INPUT})],
    [("submit_product", {"trade_name": "ACTARA 25 WG"})],
]


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


@pytest.fixture(scope="module")
def onssa():
    return Onssa(list_file=DATA / "onssa_products_2026-09-14.json")


def record(tmp_path, eu, onssa, replies, name, country):
    session = Session("test", "nvidia/nemotron-3-super-120b-a12b", folder=tmp_path)
    live = Resolver(eu, onssa, model=RecordingModel(Scripted(replies), session),
                    search=RecordingSearch(FakeSearch(PAGES), session))
    result = live.product(name, country=country)
    session.save()
    return result


def replayer(tmp_path, eu, onssa):
    store = Store(tmp_path)
    return Resolver(eu, onssa, model=ReplayModel(store), search=ReplaySearch(store))


def test_recorded_run_replays_identically_without_keys(tmp_path, eu, onssa):
    live = record(tmp_path, eu, onssa, EG_RUN, "اب جريد 46% SL", "EG")
    assert live.status == "resolved"
    again = replayer(tmp_path, eu, onssa).product("اب جريد 46% SL", country="EG")
    assert (again.status, again.value, again.substances, again.evidence) == (live.status, live.value, live.substances, live.evidence)
    assert [s["type"] for s in again.trace] == [s["type"] for s in live.trace]


def test_unrecorded_input_is_a_miss_not_a_guess(tmp_path, eu, onssa):
    record(tmp_path, eu, onssa, EG_RUN, "اب جريد 46% SL", "EG")
    with pytest.raises(ReplayMiss):
        replayer(tmp_path, eu, onssa).product("بريميوم 20% EC", country="EG")


def test_changed_tool_output_misses_instead_of_replaying_stale_answers(tmp_path, eu, onssa):
    record(tmp_path, eu, onssa, EG_RUN, "اب جريد 46% SL", "EG")
    store = Store(tmp_path)
    changed = FakeSearch({APC: (PAGES[APC][0], PAGES[APC][1] + " (page updated)")})
    r = Resolver(eu, onssa, model=ReplayModel(store), search=changed)
    with pytest.raises(ReplayMiss):
        r.product("اب جريد 46% SL", country="EG")


def test_engine_selection(tmp_path):
    assert from_env({}, store=Store(tmp_path)).mode == "rules"
    with pytest.raises(MissingKey):
        from_env({"RESIDUECHECK_ENGINE": "live"}, store=Store(tmp_path))
    Session("s1", "nvidia/nemotron-3-super-120b-a12b", folder=tmp_path).save()  # empty session: still no entries
    assert from_env({}, store=Store(tmp_path)).mode == "rules"
    s = Session("s2", "nvidia/nemotron-3-super-120b-a12b", folder=tmp_path)
    s.add("chat", {"messages": [], "tools": []}, {"content": "x", "tool_calls": [], "usage": {}})
    s.save()
    eng = from_env({}, store=Store(tmp_path))
    assert eng.mode == "replay" and eng.agent_allowed() and "no key is used" in eng.info()["note"]
    assert from_env({"RESIDUECHECK_ENGINE": "rules"}, store=Store(tmp_path)).mode == "rules"


@pytest.fixture
def client():
    yield TestClient(api.app)
    api.set_engine(Engine("rules", note=RULES_NOTE))


def check(client, product):
    return client.post("/api/check", json={"crop_code": "0110020", "harvest_on": "2026-10-01", "today": "2026-09-17",
                                           "applications": [{"product": product, "applied_on": "2026-08-15"}]}).json()


def test_api_replays_recorded_agent_and_says_so(tmp_path, eu, onssa, client):
    record(tmp_path, eu, onssa, MA_RUN, MA_INPUT, "MA")
    store = Store(tmp_path)
    api.set_engine(Engine("replay", ReplayModel(store, "nvidia/nemotron-3-super-120b-a12b"), ReplaySearch(store),
                          store=store, note="replay"))
    body = check(client, MA_INPUT)
    app0 = body["applications"][0]
    assert body["engine"]["mode"] == "replay"
    assert app0["resolution"]["method"] == "agent" and app0["resolution"]["replayed"]
    # A Moroccan name read by the model is only a suggestion; the verdict waits for the user.
    assert app0["status"] == "not_found" and app0["suggestions"] == ["ACTARA 25 WG"]
    assert body["verdict"] == "CANNOT_VERIFY"

    other = check(client, "PHYTOLIX 25 EC")["applications"][0]
    assert other["resolution"]["method"] == "rules" and "not in the recorded demo" in other["resolution"]["note"]
    alt = check(client, "ACTARA 25 WG")["applications"][0]["alternatives"]
    assert alt["method"] == "rules" and "not in the recorded demo" in alt["fallback_note"] and alt["options"]


def test_api_live_budget_cap_falls_back_to_rules(client):
    model = Scripted([])
    api.set_engine(Engine("live", model, None, daily_usd=0.0, note="live"))
    app0 = check(client, "PHYTOLIX 25 EC")["applications"][0]
    assert app0["resolution"]["method"] == "rules" and "budget" in app0["resolution"]["note"]
    assert model.seen_messages == []  # no model call was made


def test_api_rules_engine_never_calls_a_model(client):
    api.set_engine(Engine("rules", note=RULES_NOTE))
    body = check(client, "ACTARA 25 WG")
    assert body["engine"]["mode"] == "rules" and body["applications"][0]["resolution"]["method"] == "exact"
    assert body["applications"][0]["alternatives"]["method"] == "rules"
