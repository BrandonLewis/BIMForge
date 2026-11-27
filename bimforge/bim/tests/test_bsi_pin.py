"""The normative rules' pin is one shipped file, read by CI and by
est-bim validate's report (C.11)."""
from importlib.resources import files
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def pin():
    return yaml.safe_load((files("bimforge.bim") / "contract"
                           / "bsi_rules.yaml").read_text("utf-8"))


def test_the_pin_ships_with_a_repository_and_a_full_ref():
    p = pin()
    assert p["repository"] == "buildingSMART/ifc-gherkin-rules"
    assert len(p["ref"]) == 40 and int(p["ref"], 16) >= 0


def test_ci_checks_out_the_pinned_ref():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert "bimforge/bim/contract/bsi_rules.yaml" in ci
    # no second copy of the ref to drift from the file
    assert pin()["ref"] not in ci
