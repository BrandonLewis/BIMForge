"""PDF plan-sheet measurement path (v2): calibrate, vectors, regions, measure+snap, QC.

Agency plan sets are plotted from CAD, so a vector PDF's paths ARE the
geometry. This package recovers them:

  vectors.py    — harvest ``page.get_drawings()`` into flat polyline segments
                  (unrotated page points) plus positioned text spans; dash-
                  pattern feature classes (``--classes``).
  detect.py     — geometric calibration evidence that survives flattened
                  text: station ticks, grid lines, graphic scale bars.
  hints.py      — the vision handshake: the agent reads the rendered sheet
                  and writes what the flattened lettering says; the code
                  validates every hint against vector geometry.
  calibrate.py  — pooled-evidence consensus (>=2 independent source types
                  within 0.5%) deriving the page→world transform per view
                  zone (``sheet-calibration.yaml``); exits 2 with a
                  machine-readable evidence report when consensus fails.
  regions.py    — chain segments into closed loops so agents pick regions
                  instead of tracing edges (``est-bim vectors --regions``).
  snap.py       — snap agent-traced vertices onto extracted vector geometry
                  so tracing has CAD precision, not eyeball precision.
  crosscheck.py — QC gate: measured dimensions vs the engineer's lettering
                  (live text or hints), OK / REVIEW / UNVERIFIED per entity.

The output of `est-bim measure` is the same takeoff-mapped DXF that
`est-bim dxf2bim` consumes — PDF measurement is a new front door, not a new
pipeline. See docs/superpowers/specs/2026-08-02-pdf-measurement-path-design.md.

Requires pymupdf (the ``bim`` extra).
"""
