#!/usr/bin/env python3
"""Generic anchor-first placement engine.

The engine is deliberately project-agnostic. Project-specific facts live in an
authority packet. This stage computes a verified candidate plan only; it never
mutates a PcbDoc.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from collections import defaultdict
from altium_monkey import AltiumPcbDoc

STATES={"FIXED","FREE"}

def get(o,*keys):
    if isinstance(o,dict):
        for k in keys:
            if o.get(k) is not None: return o[k]
    for k in keys:
        try:
            v=getattr(o,k)
            if v is not None: return v
        except Exception: pass
    return None

def xy(o):
    for a,b in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x,y=get(o,a),get(o,b)
        try:
            if x is not None and y is not None: return float(x),float(y)
        except Exception: pass
    return None

def center(pcb,c):
    try:
        p=pcb.get_component_pick_place_center_mils(c)
        if p is not None: return float(p[0]),float(p[1])
    except Exception: pass
    try: return float(c.get_x_mils()),float(c.get_y_mils())
    except Exception: return xy(c)

def envelope(pcb,i):
    comps=list(getattr(pcb,"components",[]) or [])
    if i>=len(comps): return None
    c=comps[i]; ref=str(get(c,"designator","refdes","reference") or "")
    hits=[]
    for name in ("component_bodies","shapebased_component_bodies","regions","shapebased_regions"):
        try: items=list(getattr(pcb,name,[]) or [])
        except Exception: continue
        for body in items:
            owner=get(body,"component","component_index","owner","designator","refdes","reference")
            if owner is not None and str(owner) not in {str(i),ref}: continue
            layer=str(get(body,"layer_name","layer","mechanical_layer") or "").upper()
            if "COURTYARD" not in layer and "BODY" not in name: continue
            pts=[]
            bb=get(body,"bounding_box","bbox","bounds")
            if isinstance(bb,(list,tuple)) and len(bb)>=4:
                try: pts=[(float(bb[0]),float(bb[1])),(float(bb[2]),float(bb[3]))]
                except Exception: pts=[]
            if pts:
                xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                hits.append((min(xs),min(ys),max(xs),max(ys)))
    return hits[0] if hits else None

def overlap(a,b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

def load_authority(path):
    d=json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema")!="altium-placement-authority.v1":
        raise ValueError("unsupported placement authority schema")
    anchors=d.get("anchors",{})
    if not isinstance(anchors,dict): raise ValueError("anchors must be an object")
    for ref,v in anchors.items():
        if v.get("state") not in STATES: raise ValueError(f"invalid anchor state: {ref}")
        if v.get("state")=="FIXED" and not all(k in v for k in ("position","orientation","mechanical_envelope")):
            raise ValueError(f"fixed anchor lacks hard constraints: {ref}")
    return d

def affinity_from_manifest(path):
    d=json.loads(Path(path).read_text(encoding="utf-8"))
    intel=d.get("intelligence",d) or {}
    out=[]
    for x in intel.get("component_affinity",[]) or []:
        a,b=x.get("a"),x.get("b"); w=float(x.get("weight",0) or 0)
        if a is not None and b is not None and w>0: out.append((str(a),str(b),w))
    return out

def run(pcb_path,authority_path,manifest_path,out_path):
    authority=load_authority(authority_path)
    pcb=AltiumPcbDoc.from_file(pcb_path)
    comps=list(getattr(pcb,"components",[]) or [])
    positions={}; envelopes={}
    for i,c in enumerate(comps):
        ref=get(c,"designator","refdes","reference")
        if ref is None: continue
        ref=str(ref); positions[ref]=center(pcb,c)
        envelopes[ref]=envelope(pcb,i)

    fixed=[r for r,v in authority["anchors"].items() if v["state"]=="FIXED"]
    free=[r for r,v in authority["anchors"].items() if v["state"]=="FREE"]
    discovered=[r for r in positions if r not in authority["anchors"]]
    if authority.get("unlisted_component_policy","").startswith("FREE_IF_"):
        free=sorted(set(free)|set(discovered)-set(fixed)-set(free))
        unknown=[]
    else:
        unknown=sorted(set(discovered)-set(fixed)-set(free))

    # Unknown components are never silently optimized. They must be classified
    # by the authority layer first.
    if unknown:
        result={"schema":"altium-placement-plan.v1","status":"BLOCKED",
                "reason":"components are outside authority registry",
                "unknown_components":unknown}
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        return 1

    affinity=affinity_from_manifest(manifest_path)
    neighbors=defaultdict(list)
    for a,b,w in affinity:
        neighbors[a].append((b,w)); neighbors[b].append((a,w))

    candidates=[]
    for ref in free:
        p=positions.get(ref)
        if p is None: continue
        edges=[(o,w) for o,w in neighbors.get(ref,[]) if o in positions]
        if not edges: continue
        sw=sum(w for _,w in edges)
        target=(sum(positions[o][0]*w for o,w in edges)/sw,
                sum(positions[o][1]*w for o,w in edges)/sw)
        # The target is only a candidate. Fixed anchors are never moved.
        candidates.append({"reference":ref,"current_mils":p,
                           "candidate_target_mils":[round(target[0],3),round(target[1],3)],
                           "basis":"net-derived weighted affinity barycenter",
                           "status":"CANDIDATE"})

    result={
        "schema":"altium-placement-plan.v1",
        "status":"PLANNED",
        "mode":"ANCHOR_FIRST_NO_MUTATION",
        "authority_schema":authority["schema"],
        "fixed_anchors":fixed,
        "free_components":free,
        "candidate_count":len(candidates),
        "candidates":candidates,
        "hard_constraints":{
            "fixed_position":True,"fixed_orientation":True,
            "fixed_mechanical_envelope":True,
            "fixed_anchors_may_not_move":True
        },
        "optimization_stages":[
            "derive_functional_zones","place_free_components",
            "optimize_rotation","optimize_top_bottom",
            "check_clearance","check_assembly","verify_routing_feasibility"
        ],
        "mutation":"FORBIDDEN",
        "next_stage":"LEGALITY_AND_OBJECTIVE_EVALUATION"
    }
    Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    return 0

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--pcb",required=True,type=Path)
    ap.add_argument("--authority",required=True,type=Path)
    ap.add_argument("--connectivity-manifest",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    a=ap.parse_args()
    raise SystemExit(run(a.pcb,a.authority,a.connectivity_manifest,a.out))
