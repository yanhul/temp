#!/usr/bin/env python3
"""Extract OCR tokens and vector geometry as evidence for PDF schematic recovery.

This deliberately does NOT assign electrical nets. OCR words and geometric
intersections are candidates only; downstream symbol/pin/continuity checks must
promote them before a KiCad netlist can be considered verified.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pages", help="1-based pages/ranges, e.g. 5-13; default: all")
    ap.add_argument("--dpi", type=int, default=216)
    ap.add_argument("--min-confidence", type=float, default=20.0)
    a = ap.parse_args()
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        print(f"BLOCKED: missing PDF/OCR dependency: {exc}", file=sys.stderr)
        return 2
    src = a.pdf.resolve()
    if not src.is_file() or src.stat().st_size == 0:
        print(f"BLOCKED: PDF missing/empty: {src}", file=sys.stderr)
        return 2
    doc = fitz.open(src)
    wanted = set()
    if a.pages:
        for part in a.pages.split(","):
            if "-" in part:
                lo, hi = map(int, part.split("-", 1)); wanted.update(range(lo, hi + 1))
            else:
                wanted.add(int(part))
        if any(p < 1 or p > len(doc) for p in wanted):
            print(f"BLOCKED: page selection outside 1..{len(doc)}", file=sys.stderr); return 2
    else:
        wanted = set(range(1, len(doc) + 1))
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "pdf-schematic-page-evidence/v1",
        "source": src.name,
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "source_bytes": src.stat().st_size,
        "policy": {
            "ocr_used": True,
            "connectivity_inferred": False,
            "ocr_tokens_are_verified_labels": False,
            "vector_intersections_are_verified_junctions": False
        },
        "pages": [],
    }
    for pno in sorted(wanted):
        page = doc[pno - 1]
        scale = a.dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image_path = a.out / f"page{pno}.png"
        pix.save(image_path)
        image = Image.open(image_path)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config="--psm 11")
        tokens = []
        for i, raw in enumerate(data.get("text", [])):
            word = raw.strip()
            try: conf = float(data["conf"][i])
            except (ValueError, TypeError): conf = -1.0
            if not word or conf < 0:
                continue
            x, y, w, h = (int(data[k][i]) for k in ("left", "top", "width", "height"))
            tokens.append({
                "text": word, "confidence": conf,
                "bbox_px": [x, y, x + w, y + h],
                "bbox_pdf": [round(x / scale, 3), round(y / scale, 3),
                             round((x + w) / scale, 3), round((y + h) / scale, 3)],
                "candidate_kind": "refdes_like" if re.fullmatch(r"(?i)[A-Z]{1,4}[0-9]{1,4}[A-Z]?", word) else "text_candidate"
            })
        drawings = []
        for drawing in page.get_drawings():
            for item in drawing.get("items", []):
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    drawings.append({"kind": "line",
                        "a": [round(p1.x, 3), round(p1.y, 3)],
                        "b": [round(p2.x, 3), round(p2.y, 3)]})
                elif item[0] == "re":
                    r = item[1]
                    drawings.append({"kind": "rect",
                        "bbox": [round(r.x0, 3), round(r.y0, 3), round(r.x1, 3), round(r.y1, 3)]})
        payload = {
            "schema": "pdf-schematic-page-evidence/v1",
            "source_sha256": manifest["source_sha256"],
            "page": pno, "page_size_pdf_points": [round(page.rect.width, 3), round(page.rect.height, 3)],
            "render": {"dpi": a.dpi, "width_px": pix.width, "height_px": pix.height},
            "ocr": {"engine": "tesseract", "psm": 11, "tokens": tokens,
                    "token_count": len(tokens),
                    "tokens_at_min_confidence": sum(t["confidence"] >= a.min_confidence for t in tokens),
                    "min_confidence_threshold": a.min_confidence},
            "vector_geometry": {"line_count": sum(d["kind"] == "line" for d in drawings),
                                "rect_count": sum(d["kind"] == "rect" for d in drawings),
                                "items": drawings},
            "policy": manifest["policy"]
        }
        out = a.out / f"page{pno}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["pages"].append({
            "page": pno, "evidence_json": out.name, "evidence_bytes": out.stat().st_size,
            "render_png": image_path.name, "render_bytes": image_path.stat().st_size,
            "ocr_token_count": len(tokens),
            "tokens_at_min_confidence": payload["ocr"]["tokens_at_min_confidence"],
            "vector_line_count": payload["vector_geometry"]["line_count"],
            "vector_rect_count": payload["vector_geometry"]["rect_count"],
        })
        print(json.dumps(manifest["pages"][-1]))
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema": manifest["schema"], "source_sha256": manifest["source_sha256"],
                      "page_count": len(manifest["pages"]), "out": str(a.out),
                      "policy": manifest["policy"]}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
