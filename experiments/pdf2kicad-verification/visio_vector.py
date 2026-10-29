"""Evidence-first vector inventory for flattened/Visio schematic PDFs.
Does not infer electrical nets or emit KiCad symbols.
"""
from collections import Counter
from pathlib import Path
import json, math
import fitz
from topology_candidates import build_geometric_topology


def _xy(p):
    return [round(float(p.x), 4), round(float(p.y), 4)]


def extract_vector_page(doc, page_index, min_line_length=1.0):
    page = doc[page_index]
    paths, lines = [], []
    curves = rects = quads = 0
    for pi, drawing in enumerate(page.get_drawings()):
        kinds = Counter()
        for item in drawing.get("items", []):
            kind = item[0]
            kinds[kind] += 1
            if kind == "l":
                a, b = _xy(item[1]), _xy(item[2])
                length = math.hypot(a[0]-b[0], a[1]-b[1])
                lines.append({"a": a, "b": b, "length_pt": round(length, 4),
                              "path_index": pi, "stroke": drawing.get("color"),
                              "width_pt": drawing.get("width")})
            elif kind == "c": curves += 1
            elif kind == "re": rects += 1
            elif kind == "qu": quads += 1
        r = drawing.get("rect")
        paths.append({"path_index": pi, "type": drawing.get("type"),
                      "rect": [round(float(v), 4) for v in r] if r else None,
                      "stroke": drawing.get("color"), "fill": drawing.get("fill"),
                      "width_pt": drawing.get("width"), "item_counts": dict(kinds)})
    lines = [x for x in lines if x["length_pt"] >= min_line_length]
    words = []
    for x0, y0, x1, y1, word, block, line, wordno in page.get_text("words"):
        words.append({"text": word, "bbox": [round(v, 4) for v in (x0,y0,x1,y1)],
                      "center": [round((x0+x1)/2, 4), round((y0+y1)/2, 4)],
                      "block": block, "line": line, "word": wordno})
    ends = Counter((round(p[k][0], 2), round(p[k][1], 2))
                   for p in lines for k in ("a", "b"))
    junctions = [{"xy": list(xy), "endpoint_count": n} for xy,n in ends.items() if n >= 3]
    topology = build_geometric_topology(lines)
    return {"schema": "pdf2kicad.vector-evidence/1", "page_1based": page_index+1,
            "page_size_pt": [round(page.rect.width,4), round(page.rect.height,4)],
            "electrical_connectivity": "NOT_INFERRED",
            "geometric_topology_candidates": topology,
            "summary": {"drawings": len(paths), "lines_over_min_length": len(lines),
                        "curves": curves, "rectangles": rects, "quadrilaterals": quads,
                        "text_words": len(words), "endpoint_junction_candidates": len(junctions)},
            "paths": paths, "lines": lines, "text_words": words,
            "endpoint_junction_candidates": junctions}


def extract_pdf(pdf_path, pages, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path); summary = []
    for n in pages:
        if n < 1 or n > len(doc):
            raise ValueError(f"page out of range: {n}; PDF has {len(doc)} pages")
        result = extract_vector_page(doc, n-1)
        (out/f"vector_evidence_p{n}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        summary.append({"page": n, **result["summary"]})
    manifest = {"schema": "pdf2kicad.vector-evidence-manifest/1",
                "source": Path(pdf_path).name, "page_count": len(doc),
                "conversion_status": "BLOCKED_NO_NETLIST_ADAPTER",
                "safety_note": "Geometry inventory only. Crossings and endpoints are not proof of electrical connectivity.",
                "pages": summary}
    (out/"vector_evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("pdf"); p.add_argument("--pages", default="5,6,7,8,9,10,11,12,13")
    p.add_argument("-o", "--out", default="vector_evidence")
    a = p.parse_args()
    result = extract_pdf(a.pdf, [int(x) for x in a.pages.split(",") if x.strip()], a.out)
    for x in result["pages"]:
        print(f"page {x['page']}: lines={x['lines_over_min_length']} words={x['text_words']} endpoint-candidates={x['endpoint_junction_candidates']}")
    print("status=BLOCKED_NO_NETLIST_ADAPTER")
