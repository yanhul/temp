"""OCR evidence adapter for vectorized/outlined schematic PDFs.

Extracts text tokens and refdes-like candidates only. It does not infer symbols,
pins, nets, or electrical connectivity. Requires PyMuPDF and the Tesseract binary.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import fitz

REFDES = re.compile(r"^(?:R|C|D|L|F|J|Q|U|Y|SW|TP|FB)\d{1,3}$", re.I)


def ocr_page(doc: fitz.Document, page_number: int, dpi: int = 216, psm: int = 11) -> dict:
    if page_number < 1 or page_number > len(doc):
        raise ValueError(f"page out of range: {page_number}; PDF has {len(doc)} pages")
    if not shutil.which("tesseract"):
        raise RuntimeError("Tesseract executable not found; OCR evidence unavailable")
    page = doc[page_number - 1]
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pdf2kicad-ocr-") as td:
        png = Path(td) / "page.png"
        pix.save(png)
        proc = subprocess.run(
            ["tesseract", str(png), "stdout", "--psm", str(psm), "tsv"],
            check=False, capture_output=True, text=True, timeout=180,
        )
    if proc.returncode:
        raise RuntimeError(f"tesseract failed on page {page_number}: {proc.stderr[-1000:]}")
    rows = csv.DictReader(io.StringIO(proc.stdout), delimiter="\t")
    words = []
    for row in rows:
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row["conf"])
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        except (ValueError, KeyError):
            continue
        if not text or confidence < 0:
            continue
        words.append({
            "text": text, "confidence": confidence,
            "bbox_px": [x, y, w, h],
            "bbox_pt": [round(v / scale, 3) for v in (x, y, w, h)],
        })
    candidates = []
    for word in words:
        token = word["text"].upper().replace("—", "-").replace("–", "-")
        if REFDES.fullmatch(token):
            candidates.append({
                "candidate": token, "ocr_confidence": word["confidence"],
                "bbox_pt": word["bbox_pt"], "status": "UNVERIFIED_OCR_CANDIDATE",
            })
    return {
        "schema": "pdf2kicad.ocr-evidence/1", "page_1based": page_number,
        "render_dpi": dpi, "tesseract_psm": psm,
        "page_size_pt": [round(page.rect.width, 3), round(page.rect.height, 3)],
        "ocr_word_count": len(words), "refdes_candidate_count": len(candidates),
        "words": words, "refdes_candidates": candidates,
        "electrical_connectivity": "NOT_INFERRED",
        "warning": "OCR candidates are not verified component references, pin mappings, or nets.",
    }


def extract_pdf(pdf_path: str, pages: list[int], out_dir: str, dpi: int = 216) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    results = []
    for number in pages:
        result = ocr_page(doc, number, dpi=dpi)
        (out / f"ocr_evidence_p{number}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        results.append({
            "page": number, "ocr_words": result["ocr_word_count"],
            "refdes_candidate_occurrences": result["refdes_candidate_count"],
        })
    manifest = {
        "schema": "pdf2kicad.ocr-evidence-manifest/1",
        "source": Path(pdf_path).name, "page_count": len(doc),
        "status": "OCR_EVIDENCE_ONLY_NOT_NETLIST", "pages": results,
        "warning": "Do not infer electrical connectivity from OCR text or geometric proximity.",
    }
    (out / "ocr_evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
