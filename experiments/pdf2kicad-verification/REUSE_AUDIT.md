# PDF schematic parser reuse audit — 2026-10-29

## Decision

**Primary reuse candidate: `sphrd/SchematicNetlist` (MIT).** It already has a PDF drawing-primitive model, vector geometry extraction, wire/symbol separation, terminals, pin-number association, net labels across pages, circuit model, warnings, and a raster/OCR front end that targets the same primitive model. Its documented CLI is `schematic-netlist analyze input.pdf --pages 5-13`. Source reviewed: `src/schematic_netlist/netlist.py`, `analyze.py`, `image_extract.py`, `circuit.py`, `cli.py`, and `pyproject.toml`.

**Secondary algorithm donor: `D4NGYY/schematic-extractor` (MIT).** Useful selectively for PyMuPDF vector parsing, text bounding boxes, optional OCR fallback for outlined fonts, wire/symbol clustering, graph reconstruction, and a scope/confidence gate. Do not adopt its model/LLM layer as a prerequisite. Its README reports F1 measurements on KiCad-rendered PDFs and explicitly says legacy CAD PDFs/scans are an unverified domain shift; those figures are not predictions for this input.

## Actual input examined

Input: `[QI9-2605-A01] Module ADC(1).pdf`.

- File exists locally; size 1,561,582 bytes.
- PDF metadata: PDF 1.7; title `Visio-ModuleADC.vsdx`; producer `Microsoft: Print To PDF`.
- 16 pages.
- Pages 5–13 contain dense vector drawings (per-page vector-object counts measured with pdfplumber: 11,323; 9,320; 10,092; 5,278; 7,858; 7,143; 7,126; 7,463; 7,209). No embedded raster images on these pages.
- PyMuPDF text extraction returns only about 210–215 characters on these schematic pages, mostly the drawing title block; the circuit labels are not exposed as a normal searchable text layer. The visible schematic text appears outlined/vectorized. This is consistent with a Visio print-to-PDF path, not the Altium Smart-PDF PI/CO/NL token convention.
- The existing custom parser was run against page 5 previously and returned `0 PI`, skipped the page, then exited with `khong tim thay trang schematic nao`. **Existing conversion path: FAIL on the real input.**

## Local test evidence

- `test_pdf_profile.py`: **6 passed** (run locally on 2026-10-29).
- The profile pass was then run against pages 5–13 using the existing `pdfx.extract_page` extractor. All nine pages classify as `flattened_vector_text_candidate`, confidence `medium`, with 0 PI tokens. This is an intake classification only; it is not proof of correct symbol/pin/net reconstruction.
- Extraction profiling of pages 5–13 took about 58.85 seconds on this runtime. This is evidence of avoidable overhead in the current page extraction path, not a benchmark for either upstream project.
- The upstream projects have been source-inspected through GitHub, but **neither upstream package has been installed and executed against this exact PDF in the local runtime**. Therefore there is no upstream end-to-end PASS yet.
- Tesseract executable is present locally. That alone does not prove OCR quality or netlist correctness on this drawing.

## Why the primary candidate fits best

1. It already models vector primitives and circuit terminals/nets, instead of requiring the custom parser's `PI` token.
2. It has a documented OCR/raster path for pages whose labels are not available as PDF text. Its implementation explicitly discusses outlined text/vector drawings and OCR fallback.
3. It has an explicit warnings/log output and states that drawing-derived results must be reviewed.
4. Its dependency baseline is Python >=3.10 and core dependencies are moderate. The image extra uses OpenCV, pytesseract and NumPy; Tesseract itself remains an external executable unless using its packaged Windows app.

## Reuse boundary and strict acceptance

Do not replace the current parser with an unverified wholesale fork. Integrate as an **optional backend** behind a stable adapter, preserving provenance per page and output artifact:

- Detect PDF characteristics first (searchable text, vector-dominant, image-dominant, hybrid, Smart-PDF token signature); do not infer source CAD from geometry alone.
- Route Smart-PDF only when the actual PI/CO/NL-like evidence is present.
- Route vector/outlined Visio PDFs through the SchematicNetlist vector path plus its OCR fallback where needed.
- Use D4NGYY algorithms only where they demonstrably improve an identified weakness (text bbox association, graph/scope gate); do not add its optional YOLO/Ollama stack by default.
- Convert upstream output into the existing intermediate representation only after an explicit mapping test. Keep the upstream netlist/JSON/log as independent evidence.
- Preserve uncertain pins/nets as UNKNOWN; never synthesize a confident connection just to make a KiCad file complete.
- KiCad generation must remain blocked until refdes uniqueness, pin counts, pin-to-net evidence, unresolved warnings, and output syntax are independently checked. A structurally valid KiCad file is not proof of electrical correctness.

## Next concrete test gate

Run the upstream SchematicNetlist CLI against pages 5–13 of this exact PDF, save its JSON/netlist/log, and compare:
- detected components/refdes against a manually verified page sample;
- pin counts for each identified component;
- wire/junction and pin-to-net assignments;
- unresolved OCR labels and warnings;
- repeatability with cache disabled.

Then run the same page subset through the secondary extractor in geometric/no-detector mode. Compare outputs against the same manually reviewed ground truth. Do not compare only total component/net counts.

## Status

- Source audit: **PASS** (source/API/license inspected).
- Local profile unit tests: **PASS — 6/6**.
- Real-PDF input profiling: **PASS as classification only** (pages 5–13 correctly rejected as Smart-PDF and routed conceptually to vector/OCR path).
- Existing custom PDF-to-KiCad parser on page 5: **FAIL** (`0 PI`).
- Upstream real-PDF extraction: **NOT RUN** in this runtime; no end-to-end result claimed.
- Reuse adapter / KiCad integration: **NOT YET IMPLEMENTED**; this branch is still an experiment, not a production integration.
