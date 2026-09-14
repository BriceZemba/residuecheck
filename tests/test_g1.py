"""Checks on the committed G1 gold set (eval/gold/g1_dev.jsonl, eval/heldout/g1_heldout.jsonl)."""
import datetime
import importlib.util
import json
import pathlib

import pytest

from residuecheck.eu_data import Snapshot

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "eval" / "gold" / "g1_dev.jsonl"
HELDOUT = ROOT / "eval" / "heldout" / "g1_heldout.jsonl"


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def cases():
    return load(DEV) + load(HELDOUT)


@pytest.fixture(scope="module")
def eu():
    return Snapshot("2026-09-13")


def test_size_split_and_strata(cases):
    assert len(cases) == 120
    manifest = json.loads((ROOT / "eval" / "gold" / "g1_manifest.json").read_text(encoding="utf-8"))
    for stratum, c in manifest["strata"].items():
        rows = [x for x in cases if x["stratum"] == stratum]
        assert len(rows) == c["target"] == c["dev"] + c["heldout"]
        assert sum(x["split"] == "heldout" for x in rows) == round(c["target"] * 0.3)


def test_ids_unique_and_no_duplicate_questions(cases):
    assert len({c["id"] for c in cases}) == len(cases)
    keys = [(c["truth"].get("substance_id") or c["question"]["substance"], c["truth"]["crop_code"], c["question"]["date"]) for c in cases]
    assert len(set(keys)) == len(keys)


def test_every_truth_matches_snapshot_versions(cases, eu):
    for c in cases:
        t = c["truth"]
        if t["eu_substance"] is None:
            assert eu.substance(c["question"]["substance"]) is None
            continue
        on = datetime.date.fromisoformat(c["question"]["date"])
        versions = [m for m in eu.mrl_versions(t["residue_id"], t["crop_code"]) if m.applies_from <= on]
        last = max(versions, key=lambda m: (m.applies_from, m.applicability == "Applicable"))
        assert (last.value, last.at_loq, last.applies_from.isoformat()) == (t["mrl_mg_per_kg"], t["at_loq"], t["applies_from"]), c["id"]


def test_questions_are_phrased_not_copied(cases):
    assert all(c["question"]["substance"].strip() and c["question"]["crop"].strip() for c in cases)
    # some questions must use names other than the exact EU substance or crop name
    assert sum(c["question"]["substance"] != c["truth"]["eu_substance"] for c in cases) >= 30
    assert sum(c["question"]["crop"] != c["truth"].get("crop") for c in cases if c["truth"].get("crop")) >= 20


def test_builder_is_deterministic(tmp_path):
    spec = importlib.util.spec_from_file_location("build_g1", ROOT / "eval" / "build_g1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.OUT_DEV, mod.OUT_HELDOUT, mod.OUT_MANIFEST = tmp_path / "dev.jsonl", tmp_path / "heldout.jsonl", tmp_path / "m.json"
    mod.main()
    assert (tmp_path / "dev.jsonl").read_bytes() == DEV.read_bytes()
    assert (tmp_path / "heldout.jsonl").read_bytes() == HELDOUT.read_bytes()
