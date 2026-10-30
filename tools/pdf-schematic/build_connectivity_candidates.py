#!/usr/bin/env python3
"""Conservative vector-wire topology extraction.

Only explicit L segments are candidates. End-to-end contacts and collinear
overlaps are connected. Interior T contacts and geometric crossings are NOT
connected without an explicit junction authority (not yet implemented).
This stage never assigns symbol pins or net names.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path


def _line_segments(element, evidence_id, page):
    tag = element.get("tag")
    result = []
    def add(a, b, ordinal):
        if not (isinstance(a, list) and isinstance(b, list) and len(a) == 2 and len(b) == 2):
            return
        if all(math.isfinite(float(v)) for v in (*a, *b)) and math.dist(a, b) > 1e-8:
            result.append({"id": f"{evidence_id}:s{ordinal}", "page": page,
                           "a": [float(a[0]), float(a[1])],
                           "b": [float(b[0]), float(b[1])],
                           "evidence_id": evidence_id})
    if tag == "path":
        for i, segment in enumerate(element.get("segments", [])):
            if segment.get("type") == "L":
                pts = segment.get("points", [])
                if len(pts) == 2:
                    add(pts[0], pts[1], i)
    elif tag == "line":
        for i, segment in enumerate(element.get("segments", [])):
            if segment.get("type") == "L" and len(segment.get("points", [])) == 2:
                add(*segment["points"], i)
    elif tag in ("polyline", "polygon"):
        pts = element.get("points", [])
        for i in range(len(pts) - 1):
            add(pts[i], pts[i + 1], i)
    elif tag == "rect":
        pts = element.get("geometry", {}).get("points", [])
        for i in range(len(pts)):
            add(pts[i], pts[(i + 1) % len(pts)], i)
    return result


def _key(p, tolerance):
    return (round(p[0] / tolerance), round(p[1] / tolerance))


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _on_segment(p, a, b, eps):
    if abs(_cross(a, b, p)) > eps:
        return False
    return (min(a[0], b[0])-eps <= p[0] <= max(a[0], b[0])+eps and
            min(a[1], b[1])-eps <= p[1] <= max(a[1], b[1])+eps)


def build(ir, tolerance=0.05):
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    segments = []
    for page in ir.get("pages", []):
        for evidence in page.get("evidence", []):
            if evidence.get("origin") != "normalized_svg":
                continue
            segments.extend(_line_segments(evidence.get("geometry", {}),
                                            evidence["evidence_id"], page["page"]))

    # Nodes are exact/tolerance-bucketed endpoints only. This deliberately
    # leaves endpoint-to-interior T contacts and crossings disconnected.
    nodes = {}
    for seg in segments:
        for side in ("a", "b"):
            p = seg[side]
            key = (seg["page"], *_key(p, tolerance))
            nodes.setdefault(key, {"node_id": "n-" + hashlib.sha256(
                f"{seg['page']}:{key[1]}:{key[2]}".encode()).hexdigest()[:16],
                "page": seg["page"], "point": p, "segment_refs": []})
            nodes[key]["segment_refs"].append(seg["id"])

    parent = {key: key for key in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Merge endpoint nodes within tolerance; don't merge across pages.
    keys = list(nodes)
    for i, ka in enumerate(keys):
        pa = nodes[ka]["point"]
        for kb in keys[i+1:]:
            if ka[0] == kb[0] and math.dist(pa, nodes[kb]["point"]) <= tolerance:
                union(ka, kb)

    # Record collinear overlaps as segment-level relations. Do not merge
    # distant endpoint nodes: doing so would invent a geometric junction.
    overlap_pairs = []
    for i, sa in enumerate(segments):
        for sb in segments[i+1:]:
            if sa["page"] != sb["page"]:
                continue
            eps = tolerance * max(math.dist(sa["a"], sa["b"]), math.dist(sb["a"], sb["b"]), 1.0)
            if abs(_cross(sa["a"], sa["b"], sb["a"])) <= eps and abs(_cross(sa["a"], sa["b"], sb["b"])) <= eps:
                if (_on_segment(sa["a"], sb["a"], sb["b"], tolerance) or
                    _on_segment(sa["b"], sb["a"], sb["b"], tolerance) or
                    _on_segment(sb["a"], sa["a"], sa["b"], tolerance) or
                    _on_segment(sb["b"], sa["a"], sa["b"], tolerance)):
                    overlap_pairs.append([sa["id"], sb["id"]])

    components = {}
    for key, node in nodes.items():
        root = find(key)
        components.setdefault(root, []).append(node["node_id"])
    edges = []
    for seg in segments:
        ka = (seg["page"], *_key(seg["a"], tolerance))
        kb = (seg["page"], *_key(seg["b"], tolerance))
        edges.append({"edge_id": seg["id"], "page": seg["page"],
                      "from": nodes[ka]["node_id"], "to": nodes[kb]["node_id"],
                      "source_evidence": seg["evidence_id"],
                      "authority": "OBSERVED_VECTOR_LINE_SEGMENT"})
    return {
        "schema": "pdf-schematic-connectivity-candidates/v1",
        "status": "BLOCKED_SYMBOL_PIN_AND_JUNCTION_AUTHORITY_MISSING",
        "tolerance_pdf_points": tolerance,
        "segment_count": len(segments),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "components": [{"node_ids": sorted(v)} for v in components.values()],\n        "collinear_overlap_pairs": overlap_pairs,
        "nodes": list(nodes.values()),
        "edges": edges,
        "unknown_reasons": [
            "SYMBOL_PINS_NOT_RESOLVED",
            "T_JUNCTIONS_REQUIRE_EXPLICIT_JUNCTION_AUTHORITY",
            "CROSSINGS_ARE_NOT_CONNECTED",
            "LABEL_AND_GLOBAL_LABEL_SEMANTICS_NOT_RESOLVED",
            "NETLIST_NOT_COMPARED_WITH_NATIVE_SCHDOC",
        ],
        "policy": {
            "endpoint_contact_connects": True,
            "collinear_overlap_connects": "RECORDED_AS_SEGMENT_RELATION_NOT_MERGED_INTO_NODE_GRAPH",
            "endpoint_to_interior_contact_connects": False,
            "crossing_connects": False,
            "visual_proximity_is_not_connectivity": True,
            "pin_assignment": "NONE",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tolerance", type=float, default=0.05)
    args = ap.parse_args()
    ir = json.loads(args.ir.read_text(encoding="utf-8"))
    result = build(ir, args.tolerance)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "schema", "status", "segment_count", "node_count", "edge_count",
        "unknown_reasons")}, indent=2))


if __name__ == "__main__":
    main()
