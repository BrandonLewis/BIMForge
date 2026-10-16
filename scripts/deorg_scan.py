"""Provenance scan — CI gate (`.github/workflows/ci.yml`).

Refuses to let three things into the tree:

* an employer bid number (`B2217`, `b2235-2026-09-16`): fixtures cite public
  sources or derive their quantities in-repo, never a real pursuit;
* a developer-machine path (`/home/<user>/`, `/Users/`, `C:/Users`);
* a credential-shaped string (private-key headers, JWTs, bearer / API tokens).

Project-specific tokens (organisation and site names) are supplied by the
maintainer through the ``DEORG_EXTRA_PATTERNS`` environment variable — a
``|``-joined, case-insensitive regex, held as a repository secret so the list
never lands in the tree. Without it the three classes above still run.

    python scripts/deorg_scan.py          # exit 1 on any hit
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()


def _word(token: str) -> str:
    # boundaries that treat `_` and `-` as separators (unlike \b)
    return rf"(?<![a-z0-9]){token}(?![a-z0-9])"


BIDS = _word(r"b2[0-9]{3}")
PATHS = r"/home/[a-z][a-z0-9_-]*/|/Users/|c:/users"
SECRETS = (
    r"BEGIN [A-Z ]*PRIVATE KEY|eyJ[A-Za-z0-9_-]{10,}|"
    r"Bearer [A-Za-z0-9._-]{20,}|ApiKey [A-Za-z0-9._-]{16,}"
)


def pattern() -> re.Pattern[str]:
    parts = [BIDS, PATHS, SECRETS]
    extra = os.environ.get("DEORG_EXTRA_PATTERNS", "").strip()
    if extra:
        parts.append(extra)
    return re.compile("|".join(parts), re.I)


def tracked_files() -> list[Path]:
    try:
        # tracked AND untracked-but-not-ignored: a fresh export into an empty
        # clone has nothing staged yet, and the gate must still see it
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"], cwd=ROOT, check=True,
                             capture_output=True).stdout
        names = [n for n in out.decode("utf-8").split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        names = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                 if p.is_file() and ".git" not in p.parts]
    return [ROOT / n for n in names if n != SELF]


def scan(files: list[Path], rx: re.Pattern[str]) -> list[str]:
    hits = []
    for f in files:
        data = f.read_bytes()
        if b"\x00" in data:          # binary
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{f.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:160]}")
    return hits


def main() -> int:
    hits = scan(tracked_files(), pattern())
    if hits:
        print(">>> provenance scan found forbidden content:")
        for h in hits:
            print("  ", h)
        return 1
    extra = "with" if os.environ.get("DEORG_EXTRA_PATTERNS") else "without"
    print(f"provenance scan clean ({extra} DEORG_EXTRA_PATTERNS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
