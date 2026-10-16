# PDF schematic bridge

The kit can accept a schematic PDF without implementing a second PDF/OCR engine.

Contract:

PDF -> inspect -> extract/render -> external reconstruction backend -> .kicad_sch -> KiCad verification -> receipt

Existing tools are preferred:
- pdfinfo
- pdftotext
- pdftoppm
- tesseract
- kicad-cli / Eeschema

The bridge never treats OCR text, image proximity, or parser success as proof of electrical connectivity.

Reconstruction is an adapter boundary. A real backend must produce a .kicad_sch and its own evidence. Configure it with:

python pdf_schematic.py --pdf design.pdf --out run --backend "<command> --pdf {pdf} --out {out} --manifest {manifest}"

Without an authoritative reconstruction backend the terminal state is BLOCKED. This is deliberate: a PDF may contain visual information that is insufficient to safely infer pin/net connectivity.

AIOS should call this bridge as an execution provider. AIOS owns permit/effect/attempt lineage, retry, evidence normalization, terminal state and promotion. The provider owns PDF inspection/extraction/reconstruction/KiCad verification.

A successful parse or generated file is not a design PASS. Promotion requires source-to-schematic connectivity evidence plus KiCad verification.
