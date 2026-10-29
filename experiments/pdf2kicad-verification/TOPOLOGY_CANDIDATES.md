# Geometric topology candidate stage

This stage improves reuse of non-SmartPDF vector exports without pretending that geometry alone proves electrical connectivity.

## Input/output

- Input: straight vector strokes extracted by PyMuPDF (a, b, source line index).
- Output: geometric_topology_candidates in each vector_evidence_pN.json.
- Each source segment is split at computed segment intersections. The output retains source line indices and classifies endpoint/endpoint, endpoint/on-segment, and interior crossings.
- Collinear overlaps are deliberately not assigned a unique intersection.
- Every edge is tagged GEOMETRY_ONLY_NOT_A_NET; every intersection is tagged UNKNOWN_NO_JUNCTION_AUTHORITY.

## Why it does not emit nets

A PDF crossing may or may not be electrically connected; a dot may be absent, flattened into an image, or represented by a separate filled shape. Therefore this stage supplies a split graph for a later junction/pin association stage, but does not union nodes into nets. A downstream converter must add explicit junction-dot detection, symbol/pin anchors, label resolution and independent netlist validation before it can produce a trusted KiCad schematic.

## Test coverage

Synthetic tests cover T-junction splitting, interior crossing splitting, disjoint segments and collinear overlaps. They validate geometry only, not a real schematic's electrical correctness.
