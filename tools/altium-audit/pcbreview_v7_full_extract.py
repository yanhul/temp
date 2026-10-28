#!/usr/bin/env python3
"""Full-fidelity JSON extractor for the decoded fields supported by standalone_pcbdoc_parser.

This intentionally labels assumptions and undecoded Altium object families instead of
claiming full CAD/DRC fidelity. Original .PcbDoc is read-only.
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import standalone_pcbdoc_parser as parser


def extract(path: str) -> dict:
    pcb = parser.load_pcbdoc(path)
    connectivity = parser.analyze_connectivity(pcb)
    report = parser.build_report(pcb, path, connectivity, full=True)

    def mm(v):
        return round(parser.u2mm(v), 6) if isinstance(v, (int, float)) and math.isfinite(v) else None

    components = []
    for i, c in enumerate(pcb["components"]):
        x = parser.parse_unit(c["X"]) if c.get("X") is not None else None
        y = parser.parse_unit(c["Y"]) if c.get("Y") is not None else None
        components.append({
            "index": i, "designator": c.get("SOURCEDESIGNATOR"),
            "pattern": c.get("PATTERN"), "x_internal": x, "y_internal": y,
            "x_mm": mm(x), "y_mm": mm(y), "rotation_deg": c.get("ROTATION"),
            "layer": c.get("LAYER"), "locked_source_value": c.get("LOCKED"),
            "all_source_properties": c
        })

    pads = []
    for i, p in enumerate(pcb["pads"]):
        ci = p.get("component")
        valid_ci = isinstance(ci, int) and ci != parser.COMPONENT_NONE and 0 <= ci < len(pcb["components"])
        pads.append({
            "index": i, "name": p.get("name"), "component_index": ci,
            "component_designator": pcb["components"][ci].get("SOURCEDESIGNATOR") if valid_ci else None,
            "net_id": p.get("net"), "net_name": parser.net_name(pcb, p["net"]),
            "layer_id": p.get("layer"), "layer_name": parser.layer_name(p["layer"]),
            "x_internal": p.get("x"), "y_internal": p.get("y"), "x_mm": mm(p.get("x")), "y_mm": mm(p.get("y")),
            "top_size_internal": [p.get("topw"), p.get("toph")],
            "mid_size_internal": [p.get("midw"), p.get("midh")],
            "bottom_size_internal": [p.get("botw"), p.get("both")],
            "top_size_mm": [mm(p.get("topw")), mm(p.get("toph"))],
            "mid_size_mm": [mm(p.get("midw")), mm(p.get("midh"))],
            "bottom_size_mm": [mm(p.get("botw")), mm(p.get("both"))],
            "hole_internal": p.get("hole"), "hole_mm": mm(p.get("hole")),
            "top_shape_id": p.get("topshape"), "bottom_shape_id": p.get("botshape"),
            "rotation_deg": p.get("rot"), "pad_mode": p.get("padmode"), "plated": p.get("plated"),
            "tent_top": p.get("tent_top"), "tent_bottom": p.get("tent_bot"),
            "axis_aligned_envelope_internal": list(parser.pad_bbox(p))
        })

    tracks = []
    for i, t in enumerate(pcb["tracks"]):
        tracks.append({**t, "index": i, "layer_name": parser.layer_name(t["layer"]),
            "net_name": parser.net_name(pcb, t["net"]),
            "x1_mm": mm(t["x1"]), "y1_mm": mm(t["y1"]), "x2_mm": mm(t["x2"]),
            "y2_mm": mm(t["y2"]), "width_mm": mm(t["width"])})

    vias = []
    for i, v in enumerate(pcb["vias"]):
        vias.append({**v, "index": i, "net_name": parser.net_name(pcb, v["net"]),
            "x_mm": mm(v["x"]), "y_mm": mm(v["y"]), "diameter_mm": mm(v["diameter"]),
            "hole_mm": mm(v["hole"]), "start_layer_name": parser.layer_name(v["start"]),
            "end_layer_name": parser.layer_name(v["end"])})

    arcs = []
    for i, a in enumerate(pcb["arcs"]):
        arcs.append({**a, "index": i, "layer_name": parser.layer_name(a["layer"]),
            "net_name": parser.net_name(pcb, a["net"]), "cx_mm": mm(a["cx"]),
            "cy_mm": mm(a["cy"]), "radius_mm": mm(a["radius"]), "width_mm": mm(a["width"])})

    missing_component = sum(1 for p in pcb["pads"] if not (
        isinstance(p.get("component"), int) and p["component"] != parser.COMPONENT_NONE
        and 0 <= p["component"] < len(pcb["components"])))
    invalid_pad_nets = sum(1 for p in pcb["pads"] if p["net"] != parser.NET_NONE and not 0 <= p["net"] < len(pcb["nets"]))
    invalid_track_nets = sum(1 for t in pcb["tracks"] if t["net"] != parser.NET_NONE and not 0 <= t["net"] < len(pcb["nets"]))

    report["decoded_data"] = {
        "coordinate_unit_note": "Altium internal-unit scale used by current parser: 1 unit = 2.54e-6 mm; assumed, not independently verified",
        "nets": [{"id": i, "name": name} for i, name in enumerate(pcb["nets"])],
        "components": components, "pads": pads, "tracks": tracks, "vias": vias, "arcs": arcs,
        "board_regions": pcb["board_regions"], "dimensions": pcb["dimensions"],
        "classes": pcb["classes"], "rules_raw": pcb["rules"], "board_properties_raw": pcb["board_props"]
    }
    report["parse_coverage"] = {
        "streams": [{"name": k, **v} for k, v in sorted(pcb["streams"].items())],
        "record_counts": {k: len(pcb[k]) for k in ("nets", "components", "pads", "tracks", "vias", "arcs", "board_regions", "dimensions", "classes", "rules")},
        "record_parse_errors": pcb["parse_errors"],
        "pads_without_valid_component_mapping": missing_component,
        "pads_with_invalid_net_id": invalid_pad_nets, "tracks_with_invalid_net_id": invalid_track_nets,
        "component_mapping_status": "DECODED_UNVERIFIED",
        "net_id_to_name_status": "INDEXED_FROM_Nets6_UNVERIFIED",
        "unit_scale_status": "ASSUMED_NOT_INDEPENDENTLY_VERIFIED",
        "component_body_and_courtyard": "NOT_DECODED",
        "text_strings_and_fills": "NOT_DECODED",
        "connectivity_status": "GEOMETRIC_HEURISTIC_ONLY",
        "routing_ready": False
    }
    report["status"] = "PARSED_UNVERIFIED"
    report["audit_limitations"] = [
        "Not an Altium DRC or authoritative connectivity export.",
        "Component-to-pad indices, net IDs and internal-unit scale still require independent validation.",
        "Component body/courtyard, text/fills, polygons/regions and some primitive families are not fully decoded.",
        "Do not use this output alone to authorize automatic PCB mutation or routing."
    ]
    return report


def main():
    ap = argparse.ArgumentParser(description="Extract all currently decoded PcbDoc fields to evidence-rich JSON")
    ap.add_argument("file")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    report = extract(args.file)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FULL_EXTRACTION=PASS")
    print("STATUS=" + report["status"])
    print("SOURCE_SHA256=" + report["source"]["sha256"])
    print("COUNTS=" + json.dumps(report["counts"], sort_keys=True))
    print("PARSE_COVERAGE=" + json.dumps({k:v for k,v in report["parse_coverage"].items() if k != "streams"}, sort_keys=True))
    print("OUTPUT=" + str(out))


if __name__ == "__main__":
    main()
