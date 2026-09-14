"""ONSSA crop names -> EU crop codes. Real ONSSA records from data/onssa_cache (retrieved 2026-09-13)."""
import json
import pathlib

import pytest

from residuecheck.crops import load_map, registration
from residuecheck.eu_data import Snapshot

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
ORANGES, MANDARINS, PEACHES, APRICOTS, MELONS, TOMATOES, BASIL = \
    "0110020", "0110050", "0140030", "0140010", "0233010", "0231010", "0256080"


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


@pytest.fixture(scope="module")
def crop_map():
    return load_map()


def onssa(name):
    return json.loads((DATA / "onssa_cache" / f"{name}.json").read_text(encoding="utf-8"))


def test_every_onssa_crop_name_is_mapped(crop_map):
    names = set(json.loads((DATA / "onssa_crops_2026-09-13.json").read_text(encoding="utf-8"))["crops"])
    assert names - set(crop_map) == set()
    assert set(crop_map) - names == set()


def test_every_code_exists_in_eu_classification(eu, crop_map):
    bad = {name: code for name, e in crop_map.items() for code in e["codes"] + e.get("except_codes", [])
           if code not in eu.products}
    assert bad == {}


def test_kinds_are_known_and_non_crops_have_no_codes(crop_map):
    kinds = {"exact", "group", "narrower", "ambiguous", "nursery", "post_harvest", "non_crop"}
    assert {e["kind"] for e in crop_map.values()} <= kinds
    assert all(not e["codes"] for e in crop_map.values() if e["kind"] == "non_crop")


def test_actara_group_registration_covers_oranges_with_citrus_dar(eu):
    r = registration(onssa("ACTARA25WG"), ORANGES, eu)
    assert (r.status, r.registered_for_crop, r.dar_days) == ("registered", True, 28)
    assert {u["crop_fr"] for u in r.matched_usages} == {"Agrumes"}


def test_abamec_melon_only_is_not_registered_for_oranges(eu):
    assert registration(onssa("ABAMEC"), ORANGES, eu).status == "not_registered"
    r = registration(onssa("ABAMEC"), MELONS, eu)
    assert (r.status, r.dar_days) == ("registered", 3)


def test_stone_fruit_group_covers_apricots(eu):
    r = registration(onssa("AFROCUIVRE50WP"), APRICOTS, eu)
    assert r.status == "registered" and r.dar_days is not None


def test_storage_only_product_is_not_registered_for_a_field_crop(eu):
    # ACTELLIC 50 EC is registered for stored products and storage premises only.
    assert registration(onssa("ACTELLIC50EC"), TOMATOES, eu).status == "not_registered"


def synthetic(*crops):
    return {"usages": [{"crop_fr": c, "dar_days": d} for c, d in crops]}


def test_narrower_usage_counts_with_a_note(eu):
    r = registration(synthetic(("Agrumes: Clémentinier", 14)), MANDARINS, eu)
    assert (r.status, r.registered_for_crop, r.dar_days) == ("registered_narrower", True, 14)
    assert "Clémentinier" in r.note


def test_strictest_interval_wins_across_usages(eu):
    r = registration(synthetic(("Agrumes", 7), ("Agrumes: Oranger", 21)), ORANGES, eu)
    assert r.dar_days == 21


def test_post_harvest_and_nursery_usages_do_not_register_field_use(eu):
    assert registration(synthetic(("Agrumes: Fruits", 0)), ORANGES, eu).status == "not_registered"
    assert registration(synthetic(("Pêche", 0)), PEACHES, eu).status == "not_registered"
    assert registration(synthetic(("Tomate (pépinière)", 3)), TOMATOES, eu).status == "not_registered"


def test_ambiguous_name_is_not_confirmed(eu):
    r = registration(synthetic(("Néflier", 10)), "0130050", eu)
    assert (r.status, r.registered_for_crop) == ("ambiguous", None)


def test_except_codes_exclude_mint_code(eu):
    assert registration(synthetic(("Toutes cultures (excepté la menthe)", 3)), BASIL, eu).status == "not_registered"
    assert registration(synthetic(("Toutes cultures (excepté la menthe)", 3)), TOMATOES, eu).status == "registered"


def test_unmapped_name_gives_unknown_not_false(eu):
    r = registration(synthetic(("Culture inventée", 3)), TOMATOES, eu)
    assert (r.status, r.registered_for_crop) == ("unknown", None)
