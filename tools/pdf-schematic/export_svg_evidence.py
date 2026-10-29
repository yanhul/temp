#!/usr/bin/env python3
"""Export each PDF page to SVG and index raw vector geometry as evidence only.

No symbol recognition, wire classification, snapping, or electrical connectivity
is inferred here. SVG paths can encode text and symbol outlines as well as wires.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys
from pathlib import Path
import xml.etree.ElementTree as ET

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    src = a.pdf.resolve()
    if not src.is_file() or src.stat().st_size == 0:
        print(f"BLOCKED: missing/empty PDF: {src}", file=sys.stderr); return 2
    exe = shutil.which("pdftocairo")
    if not exe:
        print("BLOCKED: pdftocairo (poppler-utils) not installed", file=sys.stderr); return 2
    try:
        import fitz
        with fitz.open(src) as doc:
            page_count = len(doc)
    except Exception as exc:
        print(f"BLOCKED: cannot read PDF page count: {exc}", file=sys.stderr); return 2
    if page_count < 1:
        print("BLOCKED: PDF has no pages", file=sys.stderr); return 2
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "pdf-schematic-svg-evidence/v1",
        "source": src.name, "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "page_count": page_count,
        "policy": {"connectivity_inferred": False, "symbols_recognized": False,
                   "svg_paths_may_include_text_and_symbol_outlines": True,
                   "meaning": "per-page SVG and raw geometry inventory; not a netlist"},
        "pages": []
    }
    for pno in range(1, page_count + 1):
        prefix = a.out / f"page{pno}"
        cmd = [exe, "-svg", "-f", str(pno), "-l", str(pno), str(src), str(prefix)]
        run = subprocess.run(cmd, text=True, capture_output=True)
        if run.returncode:
            print(f"BLOCKED: pdftocairo page {pno} failed: {run.stderr[-2000:]}", file=sys.stderr)
            return 2
        candidates = sorted(a.out.glob(f"page{pno}*.svg"))
        if not candidates:
            print(f"BLOCKED: no SVG emitted for page {pno}", file=sys.stderr); return 2
        svg = candidates[-1]
        try:
            root = ET.parse(svg).getroot()
        except Exception as exc:
            print(f"BLOCKED: invalid SVG page {pno}: {exc}", file=sys.stderr); return 2
        counts = {}
        paths = []
        for el in root.iter():
            tag = local(el.tag)
            counts[tag] = counts.get(tag, 0) + 1
            if tag in {"path", "line", "polyline", "polygon", "rect", "circle", "ellipse"}:
                item = {"tag": tag}
                for key in ("d", "x1", "y1", "x2", "y2", "points", "x", "y", "width", "height",
                            "transform", "stroke", "stroke-width", "fill", "id", "class"):
                    if key in el.attrib:
                        item[key] = el.attrib[key]
                paths.append(item)
        raw = svg.read_bytes()
        manifest["pages"].append({
            "page": pno, "svg": svg.name, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "element_counts": counts, "geometry_element_count": len(paths),
            "geometry_json": f"page{pno}.geometry.json"
        })
        (a.out / f"page{pno}.geometry.json").write_text(
            json.dumps({"schema": "pdf-schematic-svg-geometry/v1", "page": pno,
                        "svg_sha256": hashlib.sha256(raw).hexdigest(),
                        "policy": manifest["policy"], "elements": paths},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({"schema": manifest["schema"], "source_sha256": manifest["source_sha256"],
                      "page_count": page_count, "pages": manifest["pages"],
                      "policy": manifest["policy"]}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
