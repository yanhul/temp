# Actual PDF run report — 2026-10-29

## Decision

**Status: BLOCKED for verified netlist / KiCad conversion.** This report separates extraction evidence from electrical correctness. No claim of a valid recovered schematic is made.

## Input

- File: `[QI9-2605-A01] Module ADC(1).pdf`
- Size: 1,561,582 bytes
- PDF metadata title: `Visio-ModuleADC.vsdx`
- Producer: Microsoft Print To PDF
- Total pages: 16
- Schematic pages examined: 5–13

## Actual-run evidence

### Existing Smart-PDF path

- Page 5 reports `PI=0`; pages 5–13 do not expose the expected Smart-PDF PI token signature.
- Existing Smart-PDF converter exits non-zero with `khong co trang nao du dieu kien Smart-PDF decoder`.
- This is a real-input conversion failure, and the fail-closed result is correct. It is not a conversion PASS.

### Vector evidence

The evidence-only PyMuPDF extraction completed on pages 5–13. It preserves vector lines/path metadata and searchable word bounding boxes when present. Electrical connectivity is explicitly `NOT_INFERRED`.

| Page | Line primitives ≥1 pt | Extracted PDF words | Endpoint-multiplicity candidates |
|---:|---:|---:|---:|
| 5 | 2932 | 35 | 334 |
| 6 | 2188 | 35 | 249 |
| 7 | 2202 | 35 | 299 |
| 8 | 1508 | 35 | 112 |
| 9 | 1818 | 35 | 195 |
| 10 | 1607 | 36 | 216 |
| 11 | 1615 | 36 | 225 |
| 12 | 1589 | 36 | 215 |
| 13 | 1625 | 36 | 222 |

Endpoint multiplicity is a geometric candidate only. It is not proof of an electrical junction; wire crossings, mid-segment connections and pin attachment still need semantic handling.

### OCR evidence

- Tesseract OCR was run on pages 5–13 at 216 dpi with TSV bounding boxes and confidence values.
- Batch duration recorded in the local run: 20.3 seconds.
- Words with confidence ≥20 by page: 272, 174, 138, 139, 128, 137, 128, 122, 127 (1,365 total).
- A conservative reference-designator pattern found 142 candidate occurrences / 129 distinct strings. False reads are present; this is not a verified BOM or component inventory.
- OCR words and candidates are evidence only. They must not be used alone to assign symbol identity, pin numbers, or nets.

## Local tests

- Unit tests available in the local patch directory: 8/8 PASS (profile and vector-evidence tests).
- Python compilation across local parser modules: PASS in the prior local run.
- These tests do not establish electrical correctness.
- The GitHub branch CI workflow was updated at commit `6d8009b88c635f8c717356f1cf3b0d494a74da6b` to install dependencies, compile modules and run unit tests. A completed CI run for this commit has **not been confirmed**.

## Upstream reuse

- `sphrd/SchematicNetlist` (MIT) is the primary candidate for a vector-drawing-to-netlist backend.
- `D4NGYY/schematic-extractor` (MIT) is a secondary candidate for selective geometry/text/graph algorithms.
- Their source and licenses were inspected, but neither upstream implementation has been installed and executed against this exact PDF in the current runtime. No upstream E2E result is claimed.

## Remaining blockers

1. A backend that identifies actual symbols and their pin anchors on this Visio PDF.
2. Correct handling of wire segments, junction dots, crossings, mid-segment attachments, labels, power symbols and inter-page nets.
3. Mapping each pin/net assignment to explicit geometry/text evidence and marking unresolved cases UNKNOWN.
4. An independently reviewed ground-truth subset and a pin-set/net comparison against it.
5. Only after those gates pass: generate KiCad schematic/netlist, parse with KiCad tooling where available, run electrical checks and report remaining discrepancies.

## Acceptance rule

Do not promote to PASS merely because the PDF was read, OCR ran, a KiCad file parses, or a netlist was emitted. PASS requires independently checked pin-to-net topology. Until then the correct result is `BLOCKED_NO_VERIFIED_NETLIST`.


## Follow-up verification — 2026-10-29

- Inspected extractable title text on all 16 pages of the supplied PDF. Pages 2–4 identify themselves as Part list 1–3; page 14 says `Layout Note`; page 15 says `3D View`; page 16 says `Label`. Pages 5–13 are the nine schematic sheets.
- Fixed the page-profile classifier so `Layout Note` is explicitly classified as `board_layout_candidate`, alongside BOM, 3D/render, physical-label, and document-index pages. This prevents the layout drawing from being sent through schematic OCR/topology fallback merely because it contains many vector objects.
- Added regression coverage using the actual extracted page-title phrases. GitHub Actions run [#68](https://github.com/yanhul/temp/actions/runs/40843020754), commit `e4b2c8886447c41598c7ce0f7f64fafda665285f`: compile PASS; **25/25 unit tests PASS**; required-module checks PASS.
- Scope boundary unchanged: these checks verify page routing and evidence preservation, not recovered electrical semantics. The supplied PDF has vector/OCR evidence, but no independently verified symbol-pin map, junction/crossing decisions, golden netlist comparison, or KiCad ERC evidence. Therefore full schematic conversion remains **BLOCKED**, and no fabricated `.kicad_sch`/netlist is claimed.
