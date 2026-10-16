# Security policy

bimforge reads and writes CAD and BIM files (DXF, IFC, KML/KMZ, GeoPDF, LAS/LAZ,
P6 XER, MS Project XML) that often come from third parties. A crafted input that
makes a reader execute code, read files outside the input, or exhaust memory
without bound is a security issue, not just a bug.

## Reporting

Report suspected vulnerabilities privately. Do not open a public issue: an
issue is visible to everyone the moment it is filed, before any fix exists.

1. **Preferred:** GitHub private vulnerability reporting —
   <https://github.com/BrandonLewis/BIMForge/security/advisories/new>
   ("Report a vulnerability" on the repository's Security tab). Only you and
   the maintainer can see the advisory; the fix is coordinated there and the
   advisory is published when it ships.
2. **Fallback**, if you cannot use GitHub: email
   <security@anvilrockroad.com>.

Include the input file (or a minimal reproduction), the bimforge version
(`pip show bimforge`), and what you observed.

You will get an acknowledgement within 5 business days. Fixes ship in the next
release with credit in the advisory and changelog unless you ask otherwise.

## Scope

- In scope: the `bimforge` Python package and its `est-bim` / `est-sheets` CLIs.
- Out of scope: the estimating skills and MCP servers built on top of bimforge
  (report those to their own repositories), and third-party libraries
  (ifcopenshell, ezdxf, pyproj, shapely, ...) — report upstream, and tell us so
  we can pin a fixed version.

## Supported versions

Only the latest release on PyPI receives fixes.
