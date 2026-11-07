"""`data/caltrans-2025/manifest.json` is the provenance record for the 91
Caltrans standard-plan sheets the generator families were transcribed from.

The sheets themselves are 79 MB of DGN/DXF and stay git-ignored. That is a
reasonable trade only while the manifest is committed: it is the ONLY thing
that says which sheets, from which URLs, at which sha256 — i.e. the only way
to reconstitute the inputs, or to prove that a re-download is the same
document a table was transcribed from. Ignored alongside the binaries it
described, it lived on one developer's disk, and losing that disk would have
made every catalog in `data/caltrans-2025/tables/` unverifiable against its
source.

`scripts/fetch_caltrans_dgn.py` writes this file. These tests check the
committed copy is intact and self-consistent, so a truncated or hand-edited
manifest fails here rather than years later when someone tries to re-fetch.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CALTRANS = ROOT / "data" / "caltrans-2025"
MANIFEST = CALTRANS / "manifest.json"

SHA256 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def manifest():
    assert MANIFEST.exists(), (
        f"{MANIFEST.relative_to(ROOT)} is missing. It is committed on purpose "
        "— see this module's docstring.")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_declares_its_index_and_scope(manifest):
    assert manifest["index_url"].startswith("https://dot.ca.gov/")
    assert manifest["scope"]


def test_count_matches_the_number_of_files(manifest):
    """A truncated write is the realistic corruption here, and it would leave
    `count` disagreeing with the list it summarizes."""
    assert manifest["count"] == len(manifest["files"])


def test_every_sheet_carries_a_usable_url_and_digest(manifest):
    for entry in manifest["files"]:
        sheet = entry["sheet"]
        assert entry["series"] in ("B", "D"), sheet
        assert entry["url"].startswith("https://dot.ca.gov/"), sheet
        assert entry["url"].endswith(".dgn"), sheet
        assert SHA256.match(entry["sha256"]), f"{sheet}: {entry['sha256']!r}"
        assert entry["bytes"] > 0, sheet


def test_sheets_are_unique(manifest):
    sheets = [entry["sheet"] for entry in manifest["files"]]
    assert len(set(sheets)) == len(sheets)


# Sheet -> family, using the zero-padded prefixes Caltrans actually publishes
# ("2025__b03-01a.dgn", "2025__d080.dgn").
TRANSCRIBED = {
    "b03": "retaining walls (B3 types 1/1A/5/6A/6B)",
    "d080": "single box culvert",
    "d081": "double box culvert",
    "d084": "wingwalls",
    "d089": "pipe headwalls",
}


@pytest.mark.parametrize("prefix,family", sorted(TRANSCRIBED.items()))
def test_the_transcribed_families_are_all_in_scope(manifest, prefix, family):
    """Every family with a generator traces back to a sheet listed here. If a
    future family is transcribed from a sheet outside this manifest, its
    provenance is unrecorded and this catches it."""
    sheets = [entry["sheet"] for entry in manifest["files"]]
    assert any(s.startswith(f"2025__{prefix}") for s in sheets), (
        f"no {prefix} sheet in the manifest, but the {family} family is "
        "built from it")


def verify_sheets(entries, dgn_dir):
    """Hash each manifest entry against `dgn_dir`.

    Returns ``(verified, missing, mismatched)`` rather than asserting, so the
    absent case is a RESULT the caller must handle instead of a `continue`
    that quietly shrinks the work. An interrupted fetch leaves a directory
    that exists but is partial, and a loop that skips what it cannot find
    reports the same green as one that checked all 91 sheets.
    """
    verified, missing, mismatched = [], [], []
    for entry in entries:
        path = dgn_dir / entry["sheet"]
        if not path.exists():
            missing.append(entry["sheet"])
            continue
        data = path.read_bytes()
        if (len(data) != entry["bytes"]
                or hashlib.sha256(data).hexdigest() != entry["sha256"]):
            mismatched.append(entry["sheet"])
        else:
            verified.append(entry["sheet"])
    return verified, missing, mismatched


def test_a_partial_directory_is_reported_missing_not_silently_passed(tmp_path):
    """The vacuity guard. Before this, an empty-but-present `dgn/` made the
    gated test below pass having hashed nothing at all."""
    present = b"real sheet bytes"
    entries = [
        {"sheet": "present.dgn", "bytes": len(present),
         "sha256": hashlib.sha256(present).hexdigest()},
        {"sheet": "absent.dgn", "bytes": 5, "sha256": "0" * 64},
    ]
    (tmp_path / "present.dgn").write_bytes(present)

    verified, missing, mismatched = verify_sheets(entries, tmp_path)

    assert verified == ["present.dgn"]
    assert missing == ["absent.dgn"]
    assert mismatched == []


def test_corrupt_bytes_are_reported_mismatched(tmp_path):
    entries = [{"sheet": "s.dgn", "bytes": 4, "sha256": "0" * 64}]
    (tmp_path / "s.dgn").write_bytes(b"junk")

    verified, missing, mismatched = verify_sheets(entries, tmp_path)

    assert mismatched == ["s.dgn"]
    assert verified == [] and missing == []


@pytest.mark.skipif(
    not (CALTRANS / "dgn").is_dir(),
    reason="DGN sheets are git-ignored; this runs only where they are fetched")
def test_local_sheets_match_their_recorded_digests(manifest):
    """Gated, like the table checks: it cannot run in CI because the binaries
    are deliberately absent, but where they DO exist it is the check that
    proves the manifest still describes them.

    Missing sheets FAIL rather than skip. The directory existing means someone
    fetched into it, so a shortfall is an interrupted or partial fetch — the
    condition most likely to make a digest check look green while covering
    almost nothing."""
    entries = manifest["files"]
    verified, missing, mismatched = verify_sheets(entries, CALTRANS / "dgn")

    assert not mismatched, (
        f"{len(mismatched)} sheet(s) on disk differ from the manifest "
        f"({mismatched[:5]}) — re-run scripts/fetch_caltrans_dgn.py or "
        "investigate the drift")
    assert not missing, (
        f"{len(missing)} of {len(entries)} sheets are absent from "
        f"data/caltrans-2025/dgn ({missing[:5]}) — the fetch looks partial; "
        "re-run scripts/fetch_caltrans_dgn.py")
    assert len(verified) == len(entries)
