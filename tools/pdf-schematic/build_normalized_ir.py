#!/usr/bin/env python3
"""Build a provenance-preserving intermediate representation from vector PDF evidence.

This stage intentionally does not classify electrical wires, identify symbols,
assign pin numbers, or infer connectivity. It creates stable evidence records
for downstream symbol/pin resolution and a connectivity graph solver.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg-dir", type=Path, required=True)
    ap.add_argument("--primitives", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    source = json.loads(args.primitives.read_text(encoding="utf-8"))
    source_sha = source.get("source_sha256")
    if not source_sha or source.get("schema") != "pdf-schematic-primitives/v1":
        raise SystemExit("BLOCKED: invalid or unprovenanced PDF primitive input")

    pages = []
    issues = []
    primitive_count = 0
    svg_files = sorted(args.svg_dir.glob("page*.json"))
    if len(svg_files) != source.get("totals", {}).get("pages"):
        raise SystemExit(
            f"BLOCKED: normalized SVG page count {len(svg_files)} does not match "
            f"PDF page count {source.get('totals', {}).get('pages')}"
        )

    source_pages = {int(p["page"]): p for p in source.get("pages", [])}
    for svg_path in svg_files:
        svg = json.loads(svg_path.read_text(encoding="utf-8"))
        page_no = int(svg_path.stem.removeprefix("page"))
        if svg.get("schema") != "pdf-schematic-normalized-geometry/v1":
            raise SystemExit(f"BLOCKED: invalid SVG geometry schema: {svg_path}")
        if svg.get("issue_count", 0):
            issues.extend(
                {"page": page_no, **item} for item in svg.get("issues", [])
            )
        raw_page = source_pages.get(page_no)
        if raw_page is None:
            raise SystemExit(f"BLOCKED: no raw PDF evidence for page {page_no}")

        records = []
        for index, element in enumerate(svg.get("elements", [])):
            evidence_id = "pdfv-" + digest(
                f"{source_sha}:{page_no}:svg:{index}:{json.dumps(element, sort_keys=True)}"
            )[:20]
            records.append({
                "evidence_id": evidence_id,
                "origin": "normalized_svg",
                "page": page_no,
                "ordinal": index,
                "kind": element.get("tag", "unknown"),
                "geometry": element,
                "authority": "OBSERVED_VECTOR_GEOMETRY",
                "electrical_role": "UNRESOLVED",
                "source_sha256": source_sha,
            })

        for index, span in enumerate(raw_page.get("text_spans", [])):
            evidence_id = "pdft-" + digest(
                f"{source_sha}:{page_no}:text:{index}:{json.dumps(span, sort_keys=True)}"
            )[:20]
            records.append({
                "evidence_id": evidence_id,
                "origin": "pdf_text_span",
                "page": page_no,
                "ordinal": index,
                "kind": "text_candidate",
                "geometry": {"bbox": span.get("bbox")},
                "text": span.get("text", ""),
                "font": span.get("font"),
                "font_size": span.get("size"),
                "authority": "OBSERVED_TEXT_NOT_ELECTRICAL_LABEL",
                "electrical_role": "UNRESOLVED",
                "source_sha256": source_sha,
            })

        primitive_count += len(records)
        pages.append({
            "page": page_no,
            "width_pdf_points": raw_page.get("width"),
            "height_pdf_points": raw_page.get("height"),
            "evidence": records,
            "evidence_count": len(records),
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "normalized-schematic-ir/v1",
        "source": source.get("source"),
        "source_sha256": source_sha,
        "page_count": len(pages),
        "primitive_count": primitive_count,
        "pages": pages,
        "symbols": [],
        "pins": [],
        "connectivity_edges": [],
        "symbol_count": 0,
        "resolved_pin_count": 0,
        "connectivity_edge_count": 0,
        "unknown_reasons": [
            "SYMBOL_LIBRARY_MATCHER_NOT_IMPLEMENTED",
            "PIN_GEOMETRY_AND_PIN_NUMBER_RESOLVER_NOT_IMPLEMENTED",
            "CONNECTIVITY_GRAPH_NOT_BUILT",
            "NATIVE_SCHDOC_GOLDEN_NETLIST_COMPARISON_NOT_IMPLEMENTED",
            "KICAD_SCHEMATIC_EMISSION_NOT_IMPLEMENTED",
        ],
        "geometry_issues": issues,
        "status": "BLOCKED_SYMBOL_PIN_CONNECTIVITY_UNRESOLVED",
        "policy": {
            "ocr_used": False,
            "visual_proximity_is_not_connectivity": True,
            "crossings_are_not_junctions_without_explicit_evidence": True,
            "text_is_not_promoted_to_net_label_without_resolution": True,
            "pin_numbers_are_never_guessed": True,
            "unknown_is_fail_closed": True,
        },
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": payload["schema"],
        "status": payload["status"],
        "page_count": payload["page_count"],
        "primitive_count": primitive_count,
        "geometry_issue_count": len(issues),
        "unknown_reasons": payload["unknown_reasons"],
        "output": str(args.out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
