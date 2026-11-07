#!/usr/bin/env python3
"""Fetch the 2025 Caltrans Standard Plans DGN source files we build generators from.

Scope (decided 2026-08-17):
  * Bridge standard-plan **B-series** -- all ``2025__bNN-*.dgn`` sheets
    EXCEPT the ``b15-*`` masonry soundwalls (B15-1 .. B15-15).
  * Drainage **D-series** sheets D80-D86 and D89-D91B.

Everything comes from the single "Individual Standard Plans in DGN Format (2025)"
index page; the ``xs*`` Bridge Standard *Details* page is intentionally NOT used.

The script scrapes the live index for ``.dgn`` hrefs, applies the include/exclude
rules below, downloads into a git-ignored directory, and writes a sha256 manifest.
It is idempotent (skips files already present with a matching size) and polite
(sets a UA, small inter-request delay). Pure stdlib -- no third-party deps.

    python scripts/fetch_caltrans_dgn.py            # download into data/caltrans-2025/dgn
    python scripts/fetch_caltrans_dgn.py --dry-run  # list what WOULD be fetched
    python scripts/fetch_caltrans_dgn.py --force     # re-download even if present
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

INDEX_URL = (
    "https://dot.ca.gov/programs/design/"
    "2025-ccs-standard-plans-and-standard-specifications/"
    "individual-standard-plans-in-dgn-format-2025-standards"
)
ORIGIN = "https://dot.ca.gov"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
DEFAULT_OUT = Path("data/caltrans-2025/dgn")

_HREF_RE = re.compile(r'href="([^"]*?\.dgn)"', re.IGNORECASE)

# --- selection rules, keyed on the bare filename (lower-cased) -----------------
# B-series: any 2025__bNN-*.dgn ...
_B_INCLUDE = re.compile(r"^2025__b\d", re.IGNORECASE)
# ... except the b15-* masonry soundwalls (B15-1 .. B15-15).
_B_EXCLUDE = re.compile(r"^2025__b15-", re.IGNORECASE)
# D-series: D80-D86 and D89-D91B (files are zero-padded: d080, d086c, d091b...).
_D_INCLUDE = re.compile(r"^2025__d0(8[0-6]|89|90|91)[a-z]?\.dgn$", re.IGNORECASE)


def selects(name: str) -> str | None:
    """Return 'B' / 'D' if *name* is in scope, else None."""
    low = name.lower()
    if _B_INCLUDE.match(low) and not _B_EXCLUDE.match(low):
        return "B"
    if _D_INCLUDE.match(low):
        return "D"
    return None


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def discover(index_url: str) -> list[tuple[str, str, str]]:
    """Scrape the index. Returns sorted (series, filename, absolute_url) tuples."""
    html = fetch(index_url).decode("utf-8", "replace")
    seen: dict[str, tuple[str, str, str]] = {}
    for href in _HREF_RE.findall(html):
        name = urllib.parse.unquote(href.rsplit("/", 1)[-1])
        series = selects(name)
        if series is None:
            continue
        absolute = href if href.startswith("http") else ORIGIN + href
        seen[name.lower()] = (series, name, absolute)
    return sorted(seen.values(), key=lambda t: (t[0], t[1]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--index-url", default=INDEX_URL)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    args = ap.parse_args(argv)

    print(f"Scraping index: {args.index_url}")
    targets = discover(args.index_url)
    nb = sum(1 for t in targets if t[0] == "B")
    nd = sum(1 for t in targets if t[0] == "D")
    print(f"In scope: {len(targets)} files  (B-series={nb}, D-series={nd})")

    if args.dry_run:
        for series, name, url in targets:
            print(f"  [{series}] {name:24s} {url}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    downloaded = skipped = failed = 0
    for i, (series, name, url) in enumerate(targets, 1):
        dest = args.out / name
        if dest.exists() and dest.stat().st_size > 0 and not args.force:
            data = dest.read_bytes()
            skipped += 1
            status = "skip"
        else:
            try:
                data = fetch(url)
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"  [{i}/{len(targets)}] FAIL {name}: {exc}", file=sys.stderr)
                failed += 1
                continue
            dest.write_bytes(data)
            downloaded += 1
            status = "get"
            time.sleep(args.delay)
        sha = hashlib.sha256(data).hexdigest()
        manifest.append(
            {"series": series, "sheet": name, "url": url,
             "sha256": sha, "bytes": len(data)}
        )
        print(f"  [{i}/{len(targets)}] {status:4s} [{series}] {name} ({len(data):,} B)")

    manifest_path = args.out.parent / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"index_url": args.index_url,
             "scope": "B-series (excl. b15 masonry soundwalls) + D80-D86,D89-D91B",
             "count": len(manifest), "files": manifest},
            indent=2,
        )
    )
    print(f"\nDownloaded={downloaded} skipped={skipped} failed={failed}")
    print(f"Manifest: {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
