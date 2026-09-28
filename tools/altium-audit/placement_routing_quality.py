#!/usr/bin/env python3
"""Strict placement/routing quality evaluator.

This module is evidence-only: it never moves components or mutates copper.
It measures only parser-observable facts and refuses to call a design
"optimized" when constraints or a candidate comparison are unavailable.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from altium_monkey import AltiumPcbDoc

def get(o, *keys):
    if isinstance(o, dict):
        for k in keys:
            if o.get(k) is not None:
                return o[k]
    for k in keys:
        try:
            v = getattr(o, k)
            if v is not None:
                return v
        except Exception:
            pass
    return None

def num(v):
    try:
        return float(v)
    except Exception:
        return None

def xy(o):
    for a, b in (("x_mils","y_mils"), ("location_x_mils","location_y_mils"), ("x","y")):
        x, y = num(get(o,a)), num(get(o,b))
        if x is not None and y is not None:
            return x, y
    p = get(o, "position", "location", "center")
    if isinstance(p, (tuple, list)) and len(p) >= 2:
        x, y = num(p[0]), num(p[1])
        if x is not None and y is not None:
            return x, y
    return None

def endpoint(o):
    q = [num(get(o,k)) for k in ("x1","y1","x2","y2")]
    return ((q[0],q[1]),(q[2],q[3])) if all(x is not None for x in q) else None

def seglen(o):
    e = endpoint(o)
    return math.dist(*e) if e else None

def component_position(pcb, comp):
    try:
        q = pcb.get_component_pick_place_center_mils(comp)
        if q is not None:
            return (float(q[0]), float(q[1])), "authoritative_pick_place"
    except Exception:
        pass
    try:
        return (float(comp.get_x_mils()), float(comp.get_y_mils())), "authoritative_component_position"
    except Exception:
        pass
    return xy(comp), "fallback_geometry"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--constraints", type=Path)
    ap.add_argument("--constraints", type=Path)
    args = ap.parse_args()

    pcb = AltiumPcbDoc.from_file(args.pcb)
    comps = list(getattr(pcb, "components", []) or [])
    tracks = list(getattr(pcb, "tracks", []) or [])
    arcs = list(getattr(pcb, "arcs", []) or [])
    vias = list(getattr(pcb, "vias", []) or [])
    nets = list(getattr(pcb, "nets", []) or [])

    positions = []
    for i, comp in enumerate(comps):
        p, source = component_position(pcb, comp)
        ref = get(comp, "designator", "refdes", "reference")
        positions.append({
            "component_index": i,
            "reference": str(ref) if ref is not None else None,
            "position": p,
            "evidence_source": source,
            "authoritative": source in ("authoritative_pick_place", "authoritative_component_position"),
        })

    track_lengths = [x for x in (seglen(t) for t in tracks) if x is not None]
    arc_lengths = [x for x in (seglen(a) for a in arcs) if x is not None]

    # A strict metric is useful only when its primitive evidence is complete.
    metrics = {
        "component_count": len(comps),
        "authoritative_component_positions": sum(1 for x in positions if x["authoritative"]),
        "track_count": len(tracks),
        "arc_count": len(arcs),
        "via_count": len(vias),
        "net_count": len(nets),
        "track_length_mils": sum(track_lengths) if len(track_lengths) == len(tracks) else None,
        "arc_length_mils": sum(arc_lengths) if len(arc_lengths) == len(arcs) else None,
        "copper_length_mils": (
            sum(track_lengths) + sum(arc_lengths)
            if len(track_lengths) == len(tracks) and len(arc_lengths) == len(arcs)
            else None
        ),
    }

    constraints = None
    if args.constraints and args.constraints.exists():
        try:
            constraints = json.loads(args.constraints.read_text(encoding="utf-8"))
        except Exception:
            constraints = None

    constraints = None
    if args.constraints and args.constraints.exists():
        try:
            constraints = json.loads(args.constraints.read_text(encoding="utf-8"))
        except Exception:
            constraints = None

    evidence = {
        "placement_positions_complete": bool(comps) and all(x["authoritative"] for x in positions),
        "track_geometry_complete": len(track_lengths) == len(tracks),
        "arc_geometry_complete": len(arc_lengths) == len(arcs),
        "drc_rules_available": False,
        "impedance_constraints_available": False,
        "manufacturing_constraints_available": False,
        "thermal_constraints_available": False,
        "candidate_comparison_available": bool(args.baseline and args.candidate),
        "authoritative_constraint_manifest_available": isinstance(constraints, dict) and constraints.get("schema") == "altium-placement-routing-constraints.v1",
        "authoritative_constraint_manifest_available": isinstance(constraints, dict) and constraints.get("schema") == "altium-placement-routing-constraints.v1",
    }

    missing = [k for k,v in evidence.items() if not v]
    optimization_status = "NOT_PROVEN"
    reason = (
        "Optimization is not proven: strict quality requires authoritative "
        "constraints plus a measured candidate-vs-baseline comparison. "
        "Missing evidence: " + ", ".join(missing)
    )

    comparison = None
    objective_verdict = "UNKNOWN"
    objective_verdict = "UNKNOWN"
    if args.baseline and args.candidate and args.baseline.exists() and args.candidate.exists():
        try:
            b = json.loads(args.baseline.read_text(encoding="utf-8"))
            c = json.loads(args.candidate.read_text(encoding="utf-8"))
            comparison = {"baseline": b.get("metrics",{}), "candidate": c.get("metrics",{})}
            if isinstance(constraints, dict) and constraints.get("schema") == "altium-placement-routing-constraints.v1":
                hard = constraints.get("hard_constraints", {})
                required = [k for k,v in hard.items() if v is True]
                observed = c.get("evidence", {})
                objective_verdict = "VERIFIED" if all(observed.get(k) is True for k in required) else "FAIL"
            if isinstance(constraints, dict) and constraints.get("schema") == "altium-placement-routing-constraints.v1":
                hard = constraints.get("hard_constraints", {})
                required = [k for k,v in hard.items() if v is True]
                observed = c.get("evidence", {})
                objective_verdict = "VERIFIED" if all(observed.get(k) is True for k in required) else "FAIL"
        except Exception:
            comparison = None
            reason = "Candidate/baseline artifacts exist but could not be parsed; optimization remains NOT_PROVEN."

    result = {
        "schema": "altium-placement-routing-quality.v1",
        "mode": "STRICT_EVIDENCE_ONLY",
        "optimization_status": optimization_status,
        "reason": reason,
        "metrics": metrics,
        "evidence": evidence,
        "comparison": comparison,
        "objective_verdict": objective_verdict,
        "objective_verdict": objective_verdict,
        "policy": {
            "never_claim_optimized_from_connectivity_alone": True,
            "unknown_constraint_is_not_pass": True,
            "candidate_must_be_verified_after_mutation": True,
            "baseline_must_be_immutable": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "optimization_status": optimization_status,
        "copper_length_mils": metrics["copper_length_mils"],
        "via_count": metrics["via_count"],
        "missing_evidence": missing,
    }))
    return 0 if optimization_status == "VERIFIED" else 1

if __name__ == "__main__":
    raise SystemExit(main())
