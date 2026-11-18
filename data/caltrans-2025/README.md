# Caltrans 2025 Standard Plans — sheet manifest

`manifest.json` records the Standard Plan sheets (URL and sha256 of each DGN)
that the transcribed tables came from. The sheets themselves are not included;
re-download them from the recorded URLs with `scripts/fetch_caltrans_dgn.py`.

The tables are package data now: `bimforge/caltrans/tables/2025/`, read with
`bimforge.caltrans.load_table` or a spec's `params.tables_pack`. They are
hand-transcribed dimension, quantity and reinforcement tables from the
**Caltrans Standard Plans, 2025 edition** (California Department of
Transportation, <https://dot.ca.gov/programs/design/ccs-standard-plans-and-standard-specifications>):
B3 retaining walls, D80/D81 box culverts, D84 wingwalls, D89 pipe headwalls,
D90 headwalls. Public-agency source; cite the edition when you use them.

The production-catalog tests under `bimforge/author/tests/` validate the
transcription (for example `W == C + B` on every row). Set
`BIMFORGE_CALTRANS_TABLES` to validate a copy in another directory.
