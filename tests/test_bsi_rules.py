import importlib.util
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "bsi_rules", Path(__file__).resolve().parents[1] / "scripts" / "bsi_rules.py")
bsi_rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsi_rules)

BASE = {"accepted": {"QTY001": {"why": "C.6", "outputs": ["a", "b"]}}}


def test_accepted_findings_pass():
    new, stale = bsi_rules.compare({"a": {"QTY001": [5]}, "b": {"QTY001": [7]}}, BASE)
    assert (new, stale) == ([], [])


def test_a_finding_the_baseline_does_not_list_is_new():
    new, _ = bsi_rules.compare(
        {"a": {"QTY001": [5], "IFC106": [9, 9, 3]}, "b": {"QTY001": [7]}}, BASE)
    assert new == ["a: IFC106 (#3, #9)"]


def test_a_listed_finding_no_longer_found_is_stale():
    _, stale = bsi_rules.compare({"a": {"QTY001": [5]}, "b": {}}, BASE)
    assert stale == ["b: QTY001"]


def test_an_output_not_checked_is_not_stale():
    # a run over some outputs says nothing of the others
    _, stale = bsi_rules.compare({"a": {"QTY001": [5]}}, BASE)
    assert stale == []


def test_every_baseline_entry_says_why():
    base = yaml.safe_load(bsi_rules.BASELINE.read_text("utf-8"))
    for code, entry in base["accepted"].items():
        assert entry.get("why") and entry.get("outputs"), code
