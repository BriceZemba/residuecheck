"""Rules engine v0 tests on real EU data (committed 2026-09-13 snapshot).

Seeded lots: the spray records are invented for testing; the regulatory facts they are checked against are real.
ACTARA 25 WG facts (thiamethoxam 25%, citrus, DAR 28 days) come from the ONSSA index as retrieved on 2026-09-13.
"""
import datetime

import pytest

from residuecheck.eu_data import Snapshot
from residuecheck.rules import Application, Level, Lot, evaluate

ORANGES = "0110020"
ONSSA = "https://eservice.onssa.gov.ma/IndPesticide.aspx"


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


def actara(applied_on):
    return Application("ACTARA 25 WG", applied_on, ["Thiamethoxam"], registered_for_crop=True, dar_days=28, source=ONSSA)


def test_thiamethoxam_on_oranges_after_limit_drop_is_red_and_explains_change(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [actara("2026-08-15")]), eu)
    assert r.verdict == Level.RED
    assert {"MRL_AT_LOQ", "MRL_RECENTLY_LOWERED"} <= set(r.codes())
    red = next(f for f in r.findings if f.code == "MRL_AT_LOQ")
    assert "Reg. (EU) 2023/334" in red.message and red.sources


def test_same_spray_a_season_earlier_is_amber_with_upcoming_drop(eu):
    """Arrival 2025-10-11: 0.15 mg/kg still in force, drop to 0.01 on 2026-03-07 is 147 days later."""
    r = evaluate(Lot(ORANGES, "2025-10-01", [actara("2025-08-15")]), eu)
    assert r.verdict == Level.AMBER
    assert {"NOT_APPROVED_IMPORT_TOLERANCE", "MRL_LOWERING_SOON"} <= set(r.codes())
    assert "MRL_AT_LOQ" not in r.codes()


def test_pre_harvest_interval_not_met_gives_earliest_safe_date(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01",
                     [Application("PYRIPROXYFEN 100 EC", "2026-09-20", ["Pyriproxyfen"], True, 30, ONSSA)]), eu)
    assert r.verdict == Level.RED
    assert r.codes() == ["EU_LIMIT_CHECKED", "PHI_NOT_MET"]
    assert r.earliest_safe_harvest == datetime.date(2026, 10, 20)


def test_compliant_application_is_green_and_cites_the_limit(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01",
                     [Application("PYRIPROXYFEN 100 EC", "2026-08-01", ["Pyriproxyfen"], True, 30, ONSSA)]), eu)
    assert r.verdict == Level.GREEN
    checked = [f for f in r.findings if f.code == "EU_LIMIT_CHECKED"]
    assert checked and checked[0].sources


def test_unknown_product_cannot_be_verified(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [Application("ZORBEX 300 SC", "2026-08-01", [])]), eu)
    assert r.verdict == Level.CANNOT_VERIFY
    assert r.codes() == ["PRODUCT_UNRESOLVED"]  # one finding, not a pile of derived gaps


def test_misspelled_substance_is_not_guessed(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [Application("ACTELLIC 50 EC", "2026-08-01", ["Pyrimiphos-méthyl"], True, 21)]), eu)
    assert r.verdict == Level.CANNOT_VERIFY
    assert "SUBSTANCE_UNRESOLVED" in r.codes()


def test_off_label_use_is_red(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01",
                     [Application("PYRIPROXYFEN 100 EC", "2026-08-01", ["Pyriproxyfen"], registered_for_crop=False)]), eu)
    assert r.verdict == Level.RED
    assert "NOT_REGISTERED_FOR_CROP" in r.codes()


def test_unknown_registration_blocks_green(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [Application("PYRIPROXYFEN 100 EC", "2026-08-01", ["Pyriproxyfen"])]), eu)
    assert r.verdict == Level.CANNOT_VERIFY
    assert "REGISTRATION_UNKNOWN" in r.codes()


def test_no_mrl_required_substance_is_green(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [Application("SOUFRE 80 WG", "2026-08-01", ["Sulphur"], True, 3)]), eu)
    assert r.verdict == Level.GREEN
    assert "NO_MRL_REQUIRED" in r.codes()


def test_red_outranks_cannot_verify_and_amber(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [
        actara("2026-08-15"),                                         # RED
        Application("ZORBEX 300 SC", "2026-08-01", [], True, 21),     # CANNOT_VERIFY
        Application("SPIROTETRAMAT X", "2026-08-01", ["Spirotetramat"], True, 14),  # AMBER
    ]), eu)
    assert r.verdict == Level.RED
    assert {"PRODUCT_UNRESOLVED", "NOT_APPROVED_IMPORT_TOLERANCE", "MRL_AT_LOQ"} <= set(r.codes())


def test_application_dated_after_harvest_is_flagged(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01", [actara("2026-10-05")]), eu)
    assert "APPLICATION_AFTER_HARVEST" in r.codes()
    assert r.verdict == Level.RED  # the substance check still runs and finds the LOQ limit


def test_rasff_signal_is_amber(eu):
    r = evaluate(Lot(ORANGES, "2026-10-01",
                     [Application("PYRIPROXYFEN 100 EC", "2026-08-01", ["Pyriproxyfen"], True, 30)],
                     rasff_hits={"pyriproxyfen": 2}), eu)
    assert r.verdict == Level.AMBER
    assert "RECENT_RASFF_NOTIFICATIONS" in r.codes()


def test_unsupported_crop(eu):
    r = evaluate(Lot("9999999", "2026-10-01", [actara("2026-08-15")]), eu)
    assert r.verdict == Level.CANNOT_VERIFY and r.codes() == ["CROP_NOT_SUPPORTED"]
