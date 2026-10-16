# Caltrans 2025 Standard Plans — transcribed tables

Hand-transcribed dimension, quantity and reinforcement tables from the
**Caltrans Standard Plans, 2025 edition** (California Department of
Transportation, <https://dot.ca.gov/programs/design/ccs-standard-plans-and-standard-specifications>):
B3 retaining walls, D80/D81 box culverts, D84 wingwalls, D89 pipe headwalls,
D90 headwalls. Public-agency source; cite the edition when you use them.

`manifest.json` records which sheets each table came from (URL and sha256 of
the DGN). The DGN sheets themselves are not included — re-download them from
the recorded URLs.

These tables are repository data, not package data. The production-catalog
tests under `bimforge/author/tests/` validate the transcription (for example
`W == C + B` on every row) and locate this directory through
`bimforge/author/tests/_tables.py`; set `BIMFORGE_CALTRANS_TABLES` to point
elsewhere, or let them skip when it is absent.
