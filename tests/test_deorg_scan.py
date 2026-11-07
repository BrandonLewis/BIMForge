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
