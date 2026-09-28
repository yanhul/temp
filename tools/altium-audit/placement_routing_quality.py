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



def validate_constraints(constraints):
    if not isinstance(constraints, dict) or constraints.get("schema") != "altium-placement-routing-constraints.v1":
        return False, "missing_or_wrong_schema"
    if not constraints.get("authority"):
        return False, "missing_authority"
    hard = constraints.get("hard_constraints")
    objectives = constraints.get("objectives")
    if not isinstance(hard, dict) or not isinstance(objectives, dict):
        return False, "missing_hard_constraints_or_objectives"
    if any(v is None for v in hard.values()):
        return False, "unknown_hard_constraint"
    for name, spec in objectives.items():
        if not isinstance(spec, dict) or spec.get("metric") not in {
            "copper_length_mils", "track_length_mils", "arc_length_mils", "via_count"
        } or spec.get("direction") not in {"minimize", "maximize"}:
            return False, f"invalid_objective:{name}"
    return True, None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--candidate", type=Path)
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
    constraints_error = None
    if args.constraints and args.constraints.exists():
        try:
            constraints = json.loads(args.constraints.read_text(encoding="utf-8"))
        except Exception as exc:
            constraints_error = f"invalid JSON: {type(exc).__name__}: {exc}"

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
    }

    constraints_valid, constraints_validation_error = validate_constraints(constraints)
    hard = (constraints or {}).get("hard_constraints", {}) if isinstance(constraints, dict) else {}
    objectives = (constraints or {}).get("objectives", {}) if isinstance(constraints, dict) else {}
    required_hard = [k for k,v in hard.items() if v is True]
    unknown_hard = [k for k,v in hard.items() if v is None]
    evidence["constraint_manifest_valid"] = (
        constraints_valid and not unknown_hard
    )
    missing = [k for k,v in evidence.items() if not v]
    optimization_status = "NOT_PROVEN"
    reason = (
        "Optimization is not proven: strict quality requires authoritative "
        "constraints plus a measured candidate-vs-baseline comparison. "
        "Missing evidence: " + ", ".join(missing)
    )

    comparison = None
    objective_verdict = "UNKNOWN"
    if args.baseline and args.candidate and args.baseline.exists() and args.candidate.exists():
        try:
            b = json.loads(args.baseline.read_text(encoding="utf-8"))
            c = json.loads(args.candidate.read_text(encoding="utf-8"))
            comparison = {"baseline": b.get("metrics", {}), "candidate": c.get("metrics", {})}
            observed = c.get("evidence", {})
            hard_ok = evidence["constraint_manifest_valid"] and all(observed.get(k) is True for k in required_hard)
            comparable = isinstance(b.get("metrics"), dict) and isinstance(c.get("metrics"), dict)
            objective_results = {}
            objective_unknown = []
            for name, spec in objectives.items():
                if not isinstance(spec, dict):
                    objective_unknown.append(name)
                    continue
                metric, direction = spec.get("metric"), spec.get("direction")
                bv, cv = b.get("metrics", {}).get(metric), c.get("metrics", {}).get(metric)
                if not isinstance(bv, (int,float)) or not isinstance(cv, (int,float)) or direction not in ("minimize","maximize"):
                    objective_unknown.append(name)
                    continue
                objective_results[name] = {
                    "metric": metric, "direction": direction,
                    "baseline": bv, "candidate": cv,
                    "improved": cv < bv if direction == "minimize" else cv > bv,
                    "non_worse": cv <= bv if direction == "minimize" else cv >= bv,
                }
            objective_verdict = (
                "VERIFIED"
                if hard_ok and comparable and bool(objectives) and not objective_unknown
                and all(x["non_worse"] for x in objective_results.values())
                and any(x["improved"] for x in objective_results.values())
                else ("FAIL" if hard_ok and comparable and not objective_unknown else "UNKNOWN")
            )
            comparison["objective_results"] = objective_results
            comparison["objective_unknown"] = objective_unknown
            if objective_verdict == "VERIFIED":
                optimization_status = "VERIFIED"
                reason = "Authoritative constraints are valid, hard constraints are verified, baseline/candidate metrics are comparable, and the candidate is non-worse on every declared objective with at least one strict improvement."
            elif objective_verdict == "FAIL":
                reason = "Candidate did not satisfy the strict objective policy: every declared objective must be non-worse and at least one must strictly improve."
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
        "constraint_manifest_error": constraints_error or constraints_validation_error,
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
