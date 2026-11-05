"""The pages in a browser (Playwright, optional): they render the bundle with
no console error, and the host adapter receives selections.

Skipped unless the `playwright` Python package and its Chromium are
installed (`pip install playwright && playwright install chromium`).
"""
from __future__ import annotations

import pytest

pytest.importorskip("ifcopenshell")
playwright = pytest.importorskip("playwright.sync_api")

from bimforge.web import build_bundle, write_site  # noqa: E402
from bimforge.web.tests.test_contract import OFFICIAL, TMAP, _ifc  # noqa: E402


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web")
    write_site(build_bundle(_ifc(tmp), TMAP, OFFICIAL), tmp / "site")
    return tmp / "site"


def _open(browser, site, page_name):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto((site / page_name).as_uri())
    page.wait_for_load_state("load")
    return page, errors


def test_pages_render_without_errors(site):
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                        # no browser installed
            pytest.skip(f"chromium not available: {exc}")
        page, errors = _open(browser, site, "takeoff.html")
        assert errors == []
        assert page.locator("#items tbody tr.row").count() == 3
        page.fill("#filter", "wall")
        assert page.locator("#items tbody tr.row").count() == 1
        page.fill("#filter", "")
        # the host adapter
        page.evaluate("window.bimforgeHost = {sel: [], select(ids, l) { this.sel.push([ids, l]); }}")
        page.click("#items tbody button.sel-row")
        got = page.evaluate("window.bimforgeHost.sel")
        assert len(got) == 1 and len(got[0][0]) == 2

        page, errors = _open(browser, site, "dashboard.html")
        assert errors == []
        assert page.locator("#gantt .taskrow").count() == 4
        page.click("#gantt .taskrow")
        assert "element" in page.inner_text("#taskdetail")
        page.fill("#scrubdate", "2027-03-20")
        page.dispatch_event("#scrubdate", "change")
        assert page.inner_text("#scrubday") == "2027-03-20"
        browser.close()
