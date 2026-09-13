"""Snapshot access tests against the committed 2026-09-13 EU snapshot."""
import datetime
import gzip
import json

import pytest

from residuecheck.eu_data import Snapshot, parse_date

ORANGES = "0110020"


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


def test_value_in_force_matches_database_applicable_flag(eu):
    """For every residue x crop, the version picked for the snapshot date is the one the database flags Applicable."""
    applicable = {}
    with gzip.open(eu.folder / "mrls.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["applicability_text"] == "Applicable" and r["mrl_value_only"] not in (None, ""):
                value = None if r["mrl_value_only"] == "No MRL required" else float(r["mrl_value_only"])
                applicable.setdefault((r["pesticide_residue_id"], r["product_code"]), set()).add(
                    (value, parse_date(r["application_date"])))
    mismatches = [key for key, versions in applicable.items()
                  if (lambda m: m is None or (m.value, m.applies_from) not in versions)(eu.mrl_on(*key, eu.date))]
    assert len(applicable) > 20000
    assert mismatches == []


def test_thiamethoxam_oranges_history(eu):
    sub = eu.substance("Thiamethoxam")
    assert sub["substance_status"] == "Not approved"
    (rid,) = eu.residue_ids(sub)
    before = eu.mrl_on(rid, ORANGES, "01/03/2026")
    after = eu.mrl_on(rid, ORANGES, "07/03/2026")
    assert (before.value, before.at_loq) == (0.15, False)
    assert (after.value, after.at_loq, after.regulation) == (0.01, True, "Reg. (EU) 2023/334")
    assert after.applies_from == datetime.date(2026, 3, 7)
    assert eu.previous(after).value == 0.15


@pytest.mark.parametrize("name, expected", [
    ("Thiamethoxam", "Thiamethoxam"),
    ("Abamectine", "Abamectin (aka avermectin)"),        # FR residue name, parenthetical EU name
    ("Pyriproxyfène", "Pyriproxyfen"),                  # FR with accent
    ("Pirimiphos-méthyl", "Pirimiphos-methyl"),
    ("Lambda-cyhalothrine", "lambda-Cyhalothrin"),
])
def test_substance_resolution(eu, name, expected):
    assert eu.substance(name)["substance_name"] == expected


@pytest.mark.parametrize("name", [
    "Pyrimiphos-méthyl",               # misspelling as printed in the ONSSA index
    "Cuivre - oxychlorure de cuivre",  # ONSSA formatting
    "Zorbexamide",                     # does not exist
])
def test_unresolved_names_are_not_guessed(eu, name):
    assert eu.substance(name) is None


def test_draft_regulations_are_kept_apart(eu):
    drafts = [m for versions in eu._planned.values() for m in versions]
    assert drafts and all(m.applies_from is None and m.regulation.startswith("PLAN/") for m in drafts)
