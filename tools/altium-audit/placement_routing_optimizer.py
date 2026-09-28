#!/usr/bin/env python3
"""Strict candidate evaluator for placement/routing optimization.

This tool never mutates a PCB. It creates a deterministic candidate score
from already verified artifacts. Mutation remains a separate authorized stage.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

ALLOWED={"copper_length_mils","track_length_mils","arc_length_mils","via_count"}

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline",required=True,type=Path)
    ap.add_argument("--candidates",required=True,type=Path)
    ap.add_argument("--constraints",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    a=ap.parse_args()
    base=load(a.baseline); constraints=load(a.constraints)
    if constraints.get("schema")!="altium-placement-routing-constraints.v1" or not constraints.get("authority"):
        result={"schema":"altium-placement-routing-optimizer.v1","status":"BLOCKED","reason":"authoritative constraint manifest missing or invalid"}
        a.out.write_text(json.dumps(result,indent=2),encoding="utf-8"); return 2
    objectives=constraints.get("objectives",{})
    if not isinstance(objectives,dict) or not objectives:
        result={"schema":"altium-placement-routing-optimizer.v1","status":"BLOCKED","reason":"no declared measurable objectives"}
        a.out.write_text(json.dumps(result,indent=2),encoding="utf-8"); return 2
    candidates=load(a.candidates)
    if not isinstance(candidates,list) or not candidates:
        result={"schema":"altium-placement-routing-optimizer.v1","status":"BLOCKED","reason":"no candidate artifacts"}
        a.out.write_text(json.dumps(result,indent=2),encoding="utf-8"); return 2
    scored=[]
    for c in candidates:
        metrics=c.get("metrics",{})
        if c.get("verification_status")!="VERIFIED":
            continue
        rows=[]
        valid=True
        for name,spec in objectives.items():
            metric=spec.get("metric") if isinstance(spec,dict) else None
            direction=spec.get("direction") if isinstance(spec,dict) else None
            bv,cv=base.get("metrics",{}).get(metric),metrics.get(metric)
            if metric not in ALLOWED or direction not in ("minimize","maximize") or not isinstance(bv,(int,float)) or not isinstance(cv,(int,float)):
                valid=False; break
            rows.append({"objective":name,"metric":metric,"direction":direction,"baseline":bv,"candidate":cv,
                         "non_worse":cv<=bv if direction=="minimize" else cv>=bv,
                         "improved":cv<bv if direction=="minimize" else cv>bv})
        if valid and rows and all(x["non_worse"] for x in rows) and any(x["improved"] for x in rows):
            scored.append({"candidate_id":c.get("candidate_id"),"objectives":rows})
    status="VERIFIED" if scored else "NOT_PROVEN"
    result={"schema":"altium-placement-routing-optimizer.v1","status":status,
            "policy":"candidate must already be independently VERIFIED; no mutation occurs here",
            "eligible_candidates":scored}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    return 0 if status=="VERIFIED" else 1

if __name__=="__main__": raise SystemExit(main())
