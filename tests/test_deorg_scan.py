import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "deorg_scan", Path(__file__).resolve().parents[1] / "scripts" / "deorg_scan.py")
deorg_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deorg_scan)

# Assembled at run time: written out whole, these lines would fail the scan
# they test.
HOME, USERS = "/ho" + "me/", "Us" + "ers"
BS = "\\"


def test_machine_paths_are_flagged_with_either_slash():
    rx = deorg_scan.pattern()
    for line in (HOME + "alice/x", f"/{USERS}/alice/x", f"C:/{USERS}/alice",
                 f'r"C:{BS}{USERS}{BS}alice{BS}x.exe"',
                 f'"C:{BS}{BS}{USERS}{BS}{BS}alice"'):
        assert rx.search(line), line


def test_other_drives_and_words_are_not_paths():
    rx = deorg_scan.pattern()
    for line in (f"D:{BS}data{BS}users", "the users of the scan", "c:users"):
        assert not rx.search(line), line


def test_a_jwt_is_flagged_but_not_a_globalid_with_eyj_in_it():
    rx = deorg_scan.pattern()
    assert rx.search("ey" + "JhbGciOiJIUzI1NiJ9.e30.x")
    assert not rx.search('"1IZEYJJifTDO4H7Hv3vVsg": "IfcRelDefinesByProperties"')


def test_a_pinned_globalid_that_spells_a_project_token_is_not_flagged(
        tmp_path, monkeypatch):
    monkeypatch.setenv("DEORG_EXTRA_PATTERNS", "acme")
    rx = deorg_scan.pattern()
    f = tmp_path / "pins.json"
    f.write_text('{\n  "3EiAcMeGPnSSvLDNBLCFnM": "IfcRelDefinesByProperties",\n'
                 '  "name": "Acme Bridge"\n}\n', encoding="utf-8")
    monkeypatch.setattr(deorg_scan, "ROOT", tmp_path)
    hits = deorg_scan.scan([f], rx)
    assert len(hits) == 1 and "Acme Bridge" in hits[0]
