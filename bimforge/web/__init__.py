"""bimforge.web — the JSON contract behind BIMForge's web pages, and the pages.

A page (the takeoff, the 4D/5D dashboard) is a view of ONE JSON document,
the *bundle*, that `contract.build_bundle` produces headlessly from an IFC:
elements, pay-item takeoff, the 4D schedule with its element links, the 5D
costs, and each element's appear / vanish dates. The pages never parse IFC
and never know where the bundle came from, so the same page runs in two
hosts:

* standalone — `est-bim web` writes the bundle and the pages into a
  directory and serves it (or you put it behind any web server);
* inside an editor — a bridge (a Blender add-on) serves the same pages and
  the same bundle from the open file, and provides `window.bimforgeHost`
  so a click on an element selects it there.

The contract is versioned (`contract.CONTRACT`); a page refuses a bundle
of another major version rather than guess.
"""
from bimforge.web.contract import CONTRACT, build_bundle, validate_bundle
from bimforge.web.site import serve_site, write_site

__all__ = ["CONTRACT", "build_bundle", "validate_bundle", "serve_site",
           "write_site"]
