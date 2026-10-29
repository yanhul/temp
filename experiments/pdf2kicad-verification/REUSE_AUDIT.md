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
- `python -m py_compile` across the 12 local Python modules: **exit 0** when using a separate bytecode cache directory (the mounted archive's existing `__pycache__` was not writable; that was an environment permission issue, not a syntax error).
- Real invocation after the page-selection optimization: `main.py '[QI9-2605-A01] Module ADC(1).pdf' -o /mnt/data/pdf2kicad_actual_test5 --pages 5`: **exit 1**, 4.30 seconds; reports `flattened_vector_text_candidate` (`PI=0, text=19, vector=11323, images=0`) and safely stops with `khong co trang nao du dieu kien Smart-PDF decoder`. This is the expected fail-closed behavior, not a successful conversion.
- The profile pass was then run against pages 5–13 using the existing `pdfx.extract_page` extractor. All nine pages classify as `flattened_vector_text_candidate`, confidence `medium`, with 0 PI tokens. This is an intake classification only; it is not proof of correct symbol/pin/net reconstruction.
- After changing `pdfx.py` to pass `page_numbers={page_no}` into pdfminer for both page extraction and page-size lookup, profiling pages 5–13 completed in 20.48 seconds on this runtime. The prior page selection implementation re-iterated the whole PDF per requested page; this change limits pdfminer to the requested page. This is a local performance result, not an upstream benchmark.
- The upstream projects have been source-inspected through GitHub, but **neither upstream package has been installed and executed against this exact PDF in the local runtime**. A local `git clone` attempt failed because this runtime cannot resolve `github.com`; therefore no upstream end-to-end result is claimed. The source API and dependency metadata were reviewed via GitHub connector.
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


## Follow-up implementation — 2026-10-29 (actual PDF vector evidence)

A new optional, evidence-only backend was added: `visio_vector.py`. It uses PyMuPDF to preserve vector line primitives, path metadata, text word bounding boxes, and exact-coordinate endpoint multiplicity candidates. It deliberately marks electrical connectivity as `NOT_INFERRED`; endpoint multiplicity is not treated as a net or junction proof. The existing Smart-PDF conversion path is unchanged.

- New regression tests: `test_visio_vector.py`.
- Local full Python compile: **PASS**.
- Local unit suite: **8/8 PASS** (the six profile tests plus two vector-evidence tests).
- Real input run: pages 5–13 successfully exported into a JSON vector-evidence manifest and per-page evidence files. The manifest reports 1,508–2,932 line primitives at least 1 pt long per page, and 35–36 extracted text words per page.
- Real conversion status remains **BLOCKED_NO_NETLIST_ADAPTER**. The vector inventory proves we can extract drawing evidence from this Visio PDF; it does not prove component recognition, pin association, wire identity, or electrical connectivity. No KiCad schematic/netlist was generated by this backend.
- GitHub Actions syntax-check workflow was observed queued for commit `14f33c5d553f7d2e8b365df439a07beef671383f`; do not call CI passing until a completed result is fetched.

This is a safe fallback/intake layer, not a replacement for the primary SchematicNetlist backend and not permission to merge the draft PR.
