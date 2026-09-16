"""Resolver tests: deterministic paths on real data, agent loop and verifier with a scripted model and fake search.

The scripted replies stand in for Nemotron until Token Factory billing works; they exercise the same loop,
tool dispatch and verification code the real model will go through.
"""
import pytest

from residuecheck.eu_data import Snapshot
from residuecheck.llm import Scripted, TokenFactory
from residuecheck.onssa import DATA, Onssa
from residuecheck.resolver import Resolver
from residuecheck.search import FakeSearch, MissingKey

NPIC = "https://npic.orst.edu/factsheets/archive/cuso4tech.html"
PPDB = "https://sitem.herts.ac.uk/aeru/ppdb/en/Reports/178.htm"
APC = "http://www.apc.gov.eg/ar/PesticideDetails.aspx?id=11719"
BLOG = "https://example-agri-blog.com/ab-greed"
PAGES = {
    NPIC: ("Copper Sulfate Technical Fact Sheet",
           "Copper sulfate is a fungicide. When it is mixed with calcium hydroxide it is known as Bordeaux mixture."),
    PPDB: ("Pyrethrins (Ref: pyrethrum)", "Pyrethrins are natural insecticides extracted from pyrethrum flowers (Pyrèthre)."),
    APC: ("بيانات مبيد", "الإسم التجاري اب جريد 46% SL المواد الفعالة Bentazone + MCPA التركيز 40 + 6 الموقف من التسجيل مسجل"),
    BLOG: ("AB Greed herbicide review", "AB Greed contains bentazone and MCPA."),
}


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


@pytest.fixture(scope="module")
def onssa():
    return Onssa(list_file=DATA / "onssa_products_2026-09-14.json")


def resolver(eu, onssa, replies=None, pages=PAGES):
    model = Scripted(replies) if replies is not None else None
    return Resolver(eu, onssa, model=model, search=FakeSearch(pages) if replies is not None else None)


# Deterministic paths (no model)

def test_exact_product_needs_no_model(eu, onssa):
    r = resolver(eu, onssa).product("actara 25 wg")
    assert (r.status, r.value, r.model_calls) == ("exact", "ACTARA 25 WG", 0)


@pytest.mark.parametrize("written, expected", [
    ("KUIVREVAL 20 WG", "CUIVREVAL 20 WG"),   # C/K swap
    ("CR0NOS", "CRONOS"),                     # O/0
    ("SOUPYTO", "SOUPHYTO"),                  # dropped letter
    ("ZOXYBIN", "ZOXYBIN 25 SC"),             # formulation code missing
])
def test_typos_become_suggestions_not_silent_fixes(eu, onssa, written, expected):
    r = resolver(eu, onssa).product(written)
    assert (r.status, r.value) == ("suggested", expected)
    assert not r.confirmed


def test_fake_product_is_not_found(eu, onssa):
    r = resolver(eu, onssa).product("PHYTOLIX 25 EC")
    assert r.status == "not_found" and r.value is None


def test_exact_substance_needs_no_model(eu, onssa):
    r = resolver(eu, onssa).substance("Boscalide")
    assert (r.status, r.value) == ("exact", "Boscalid (formerly nicobifen)") and r.residue_ids


def test_hard_substance_without_model_cannot_be_verified(eu, onssa):
    assert resolver(eu, onssa).substance("Pyrèthre").status == "cannot_verify"


def test_token_factory_client_requires_key(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(MissingKey):
        TokenFactory()


# Agent + verifier (scripted model)

def test_substance_mapping_accepted_when_evidence_supports_it(eu, onssa):
    r = resolver(eu, onssa, [
        [("web_search", {"query": "sulfate tétracuivrique tricalcique fungicide"})],
        [("eu_search", {"keyword": "bordeaux"})],
        [("submit_substance", {"eu_name": "Bordeaux mixture", "evidence_url": NPIC})],
    ]).substance("Cuivre - sulfate tétracuivrique tricalcique")
    assert (r.status, r.value) == ("resolved", "Bordeaux mixture")
    copper = eu.residue_ids(eu.substance("Copper oxychloride"))
    assert set(r.residue_ids) & set(copper)  # same copper residue definition
    assert r.model_calls == 3 and [s["type"] for s in r.trace][-1] == "submit"


def test_invented_url_is_rejected(eu, onssa):
    r = resolver(eu, onssa, [
        [("submit_substance", {"eu_name": "Pyrethrins", "evidence_url": "https://made-up.example/pyrethrins"})],
    ]).substance("Pyrèthre")
    assert r.status == "cannot_verify" and "not returned by any tool" in r.reason
    assert r.trace[-1] == {"type": "verifier", "decision": "rejected", "why": "evidence URL was not returned by any tool in this run"}


def test_page_that_does_not_mention_the_substance_is_rejected(eu, onssa):
    r = resolver(eu, onssa, [
        [("web_search", {"query": "copper sulfate fungicide"})],
        [("submit_substance", {"eu_name": "Pyrethrins", "evidence_url": NPIC})],  # NPIC page is about copper
    ]).substance("Pyrèthre")
    assert r.status == "cannot_verify" and "does not mention Pyrethrins" in r.reason


def test_non_eu_name_is_rejected(eu, onssa):
    r = resolver(eu, onssa, [
        [("web_search", {"query": "pyrethrum flowers insecticide"})],
        [("submit_substance", {"eu_name": "Natural pyrethrum extract", "evidence_url": PPDB})],
    ]).substance("Pyrèthre")
    assert r.status == "cannot_verify" and "not an EU database substance name" in r.reason


def test_family_name_needs_confirmation(eu, onssa):
    pages = {"https://example.org/paraffin": ("Paraffin oil", "Horticultural paraffin oil, mineral oil for pest control.")}
    r = resolver(eu, onssa, [
        [("web_search", {"query": "huile minérale paraffinique mineral oil"})],
        [("submit_substance", {"eu_name": "Paraffin oil", "evidence_url": "https://example.org/paraffin"})],
    ], pages=pages).substance("Huile minérale paraffinique")
    assert r.status == "needs_confirmation" and len(r.candidates) > 5
    assert all(c.startswith("Paraffin oil/(CAS") for c in r.candidates)


def test_model_cannot_confirm_a_moroccan_product_that_does_not_exist(eu, onssa):
    r = resolver(eu, onssa, [
        [("submit_product", {"trade_name": "ZORBEX 300 SC"})],
    ]).product("ZORBX")  # too far from any real name for the fuzzy step
    assert r.status == "not_found" and "not a name in the ONSSA index" in r.reason


def test_model_reading_of_a_moroccan_name_is_only_a_suggestion(eu, onssa):
    r = resolver(eu, onssa, [
        [("onssa_similar", {"name": "ACT 25"})],
        [("submit_product", {"trade_name": "ACTARA 25 WG"})],
    ]).product("ACT 25")
    assert (r.status, r.value) == ("suggested", "ACTARA 25 WG") and not r.confirmed


def test_foreign_product_resolved_from_official_register(eu, onssa):
    r = resolver(eu, onssa, [
        [("web_search", {"query": "اب جريد 46% SL", "official_register_only": True})],
        [("submit_product", {"trade_name": "اب جريد 46% SL", "active_substances": ["Bentazone", "MCPA"], "evidence_url": APC})],
    ]).product("اب جريد 46% SL", country="EG")
    assert (r.status, r.value, r.substances) == ("resolved", "اب جريد 46% SL", ["Bentazone", "MCPA"])
    assert r.evidence[0]["url"] == APC


def test_foreign_product_from_unofficial_page_is_rejected(eu, onssa):
    r = resolver(eu, onssa, [
        [("web_search", {"query": "AB Greed herbicide"})],
        [("submit_product", {"trade_name": "AB Greed", "active_substances": ["Bentazone", "MCPA"], "evidence_url": BLOG})],
    ]).product("AB Greed", country="EG")
    assert r.status == "not_found" and "not from the official register" in r.reason


def test_foreign_product_with_unconfirmed_substance_is_rejected(eu, onssa):
    r = resolver(eu, onssa, [
        [("web_search", {"query": "اب جريد", "official_register_only": True})],
        [("submit_product", {"trade_name": "اب جريد 46% SL", "active_substances": ["Bentazone", "Glyphosate"], "evidence_url": APC})],
    ]).product("اب جريد 46% SL", country="EG")
    assert r.status == "not_found" and "Glyphosate" in r.reason


def test_extract_only_allowed_for_urls_seen_in_search(eu, onssa):
    res = resolver(eu, onssa, [
        [("web_extract", {"url": PPDB})],  # not returned by a search first
        [("submit_substance", {"eu_name": "Pyrethrins", "evidence_url": PPDB})],
    ]).substance("Pyrèthre")
    assert res.status == "cannot_verify"
    tool_step = [s for s in res.trace if s["type"] == "tool"][0]
    assert "only URLs returned by web_search" in tool_step["result"]["error"]


def test_step_limit_gives_cannot_verify(eu, onssa):
    r = resolver(eu, onssa, ["thinking...", "still thinking...", "hmm", "no", "no", "no"]).substance("Pyrèthre")
    assert r.status == "cannot_verify" and "no answer within" in r.reason and r.model_calls == 6
