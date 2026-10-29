#!/usr/bin/env python3
"""Extract reusable, provenance-preserving primitives from vector/text PDF schematics.

This is an intake/IR stage, not a netlist solver. It never infers electrical
connectivity from visual proximity. Unknown connectivity remains unknown.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        import fitz
    except ImportError:
        print("BLOCKED: install PyMuPDF (pymupdf)", file=sys.stderr)
        return 2
    src = args.pdf.resolve()
    if not src.is_file() or src.stat().st_size == 0:
        print(f"BLOCKED: PDF input missing/empty: {src}", file=sys.stderr)
        return 2
    doc = fitz.open(src)
    pages = []
    totals = {"pages": len(doc), "text_chars": 0, "text_spans": 0,
              "drawing_items": 0, "lines": 0, "rects": 0, "curves": 0,
              "images": 0}
    for page_no, page in enumerate(doc, 1):
        raw = page.get_text("dict")
        spans = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if text.strip():
                        spans.append({"text": text, "bbox": [round(float(v), 3) for v in span.get("bbox", [])],
                                      "font": span.get("font"), "size": round(float(span.get("size", 0)), 3),
                                      "flags": span.get("flags")})
        drawings = []
        for drawing in page.get_drawings():
            items = []
            for item in drawing.get("items", []):
                kind = item[0]
                entry = {"kind": kind}
                if kind == "l":
                    entry["points"] = [[round(float(p.x), 3), round(float(p.y), 3)] for p in item[1:]]
                    totals["lines"] += 1
                elif kind == "re":
                    r = item[1]
                    entry["rect"] = [round(float(v), 3) for v in [r.x0, r.y0, r.x1, r.y1]]
                    totals["rects"] += 1
                elif kind == "c":
                    entry["points"] = [[round(float(p.x), 3), round(float(p.y), 3)] for p in item[1:]]
                    totals["curves"] += 1
                elif kind == "qu":
                    q = item[1]
                    entry["points"] = [[round(float(p.x), 3), round(float(p.y), 3)] for p in [q.ul, q.ur, q.lr, q.ll]]
                items.append(entry)
            drawings.append({"items": items, "rect": [round(float(v), 3) for v in
                            [drawing["rect"].x0, drawing["rect"].y0, drawing["rect"].x1, drawing["rect"].y1]],
                            "color": drawing.get("color"), "fill": drawing.get("fill"),
                            "width": drawing.get("width")})
            totals["drawing_items"] += len(items)
        image_count = len(page.get_images(full=True))
        totals["images"] += image_count
        text = page.get_text("text")
        totals["text_chars"] += len(text)
        totals["text_spans"] += len(spans)
        pages.append({"page": page_no, "width": round(page.rect.width, 3),
                      "height": round(page.rect.height, 3), "text": text,
                      "text_spans": spans, "drawings": drawings, "image_count": image_count})
    payload = {"schema": "pdf-schematic-primitives/v1",
               "source": src.name, "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
               "source_bytes": src.stat().st_size,
               "policy": {"ocr_used": False, "connectivity_inferred": False,
                          "meaning": "geometric/text primitives only; not an electrical netlist"},
               "totals": totals, "pages": pages}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: v for k, v in payload.items() if k != "pages"}
    summary["page_summaries"] = [{"page": p["page"], "text_chars": len(p["text"]),
                                  "text_spans": len(p["text_spans"]),
                                  "drawing_paths": len(p["drawings"]),
                                  "drawing_items": sum(len(d["items"]) for d in p["drawings"]),
                                  "images": p["image_count"]} for p in pages]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if totals["pages"] == 0:
        print("BLOCKED: PDF has no pages", file=sys.stderr); return 2
    if totals["text_chars"] == 0 and totals["drawing_items"] == 0 and totals["images"] == 0:
        print("BLOCKED: no extractable text/vector/image content", file=sys.stderr); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
