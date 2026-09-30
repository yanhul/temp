#!/usr/bin/env python3
"""Generic anchor-first placement planner.

Two execution profiles are supported:
- generic: all fixed/optimizable decisions come from an authority packet.
- QI9: the QI9 authority packet fixes J1/J2/J3/J4/J5/J7/U15.

This module is planning-only. It never mutates a PcbDoc.
"""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from pathlib import Path
from altium_monkey import AltiumPcbDoc

STATES={"FIXED","FREE"}
LAYERS=("TOP","BOTTOM")
ROTATIONS=(0.0,90.0,180.0,270.0)

def get(o,*keys):
    if isinstance(o,dict):
        for k in keys:
            if o.get(k) is not None:return o[k]
    for k in keys:
        try:
            v=getattr(o,k)
            if v is not None:return v
        except Exception: pass
    return None

def xy(o):
    for a,b in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x,y=get(o,a),get(o,b)
        try:
            if x is not None and y is not None:return float(x),float(y)
        except Exception: pass
    return None

def center(pcb,c):
    try:
        p=pcb.get_component_pick_place_center_mils(c)
        if p is not None:return float(p[0]),float(p[1])
    except Exception: pass
    try:return float(c.get_x_mils()),float(c.get_y_mils())
    except Exception:return xy(c)

def orientation(c):
    for k in ("rotation","rotation_degrees","orientation","angle"):
        v=get(c,k)
        try:
            if v is not None:return float(v)
        except Exception: pass
    return 0.0

def layer(c):
    v=get(c,"layer","layer_name","side","layer_ref")
    s=str(v or "").upper()
    if "BOTTOM" in s:return "BOTTOM"
    return "TOP"

def envelope(pcb,i):
    comps=list(getattr(pcb,"components",[]) or [])
    if i>=len(comps):return None
    c=comps[i]; ref=str(get(c,"designator","refdes","reference") or "")
    found=[]
    for name in ("component_bodies","shapebased_component_bodies","regions","shapebased_regions"):
        try:items=list(getattr(pcb,name,[]) or [])
        except Exception:continue
        for body in items:
            owner=get(body,"component","component_index","owner","designator","refdes","reference")
            if owner is not None and str(owner) not in {str(i),ref}:continue
            lname=str(get(body,"layer_name","layer","mechanical_layer") or "").upper()
            if name in ("regions","shapebased_regions") and "COURTYARD" not in lname:continue
            bb=get(body,"bounding_box","bbox","bounds")
            if isinstance(bb,(list,tuple)) and len(bb)>=4:
                try:found.append(tuple(float(x) for x in bb[:4]))
                except Exception:pass
    return found[0] if found else None

def shifted_box(box,old,new,rotation_delta=0.0):
    if not box:return None
    cx=(box[0]+box[2])/2; cy=(box[1]+box[3])/2
    w=abs(box[2]-box[0]); h=abs(box[3]-box[1])
    if int(round(rotation_delta))%180: w,h=h,w
    dx,dy=new[0]-old[0],new[1]-old[1]
    return (new[0]-w/2,new[1]-h/2,new[0]+w/2,new[1]+h/2)

def overlap(a,b):
    return not(a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

def load_authority(path):
    d=json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema")!="altium-placement-authority.v1":
        raise ValueError("unsupported placement authority schema")
    anchors=d.get("anchors")
    if not isinstance(anchors,dict):raise ValueError("anchors must be an object")
    for ref,v in anchors.items():
        if v.get("state") not in STATES:raise ValueError(f"invalid anchor state: {ref}")
        if v.get("state")=="FIXED" and not all(k in v for k in ("position","orientation","mechanical_envelope")):
            raise ValueError(f"fixed anchor lacks hard constraints: {ref}")
    return d

def affinity_from_manifest(path):
    d=json.loads(Path(path).read_text(encoding="utf-8"))
    intel=d.get("intelligence",d) or {}
    out=[]
    for x in intel.get("component_affinity",[]) or []:
        a,b=x.get("a"),x.get("b"); w=float(x.get("weight",0) or 0)
        if a is not None and b is not None and w>0:out.append((str(a),str(b),w))
    return out

def run(pcb_path,authority_path,manifest_path,out_path):
    authority=load_authority(authority_path)
    pcb=AltiumPcbDoc.from_file(pcb_path)
    comps=list(getattr(pcb,"components",[]) or [])
    positions={}; orientations={}; layers={}; envelopes={}
    for i,c in enumerate(comps):
        ref=get(c,"designator","refdes","reference")
        if ref is None:continue
        ref=str(ref); positions[ref]=center(pcb,c); orientations[ref]=orientation(c); layers[ref]=layer(c); envelopes[ref]=envelope(pcb,i)

    fixed=[r for r,v in authority["anchors"].items() if v["state"]=="FIXED"]
    declared_free=[r for r,v in authority["anchors"].items() if v["state"]=="FREE"]
    discovered=sorted(r for r in positions if r not in authority["anchors"])
    if str(authority.get("unlisted_component_policy","")).startswith("FREE_IF_"):
        free=sorted(set(declared_free)|set(discovered)-set(fixed)-set(declared_free)); unknown=[]
    else:
        free=declared_free; unknown=discovered

    missing_fixed=sorted(set(fixed)-set(positions))
    if missing_fixed:
        result={"schema":"altium-placement-plan.v2","status":"BLOCKED","mode":authority.get("mode"),
                "reason":"declared fixed anchor missing from PcbDoc","missing_fixed_anchors":missing_fixed}
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False)); return 1
    if unknown:
        result={"schema":"altium-placement-plan.v2","status":"BLOCKED","mode":authority.get("mode"),
                "reason":"components are outside authority registry","unknown_components":unknown}
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False)); return 1

    # Fixed anchors are immutable by contract. Capture their observed state so a
    # later mutation/verification stage can compare it byte-for-byte at the
    # semantic level (position, orientation, side, envelope source).
    fixed_snapshot={r:{"position":positions[r],"orientation":orientations[r],"layer":layers[r],
                       "mechanical_envelope_source":authority["anchors"][r]["mechanical_envelope"]} for r in fixed}

    affinity=affinity_from_manifest(manifest_path)
    neighbors=defaultdict(list)
    for a,b,w in affinity:
        if a in positions and b in positions:
            neighbors[a].append((b,w)); neighbors[b].append((a,w))

    candidates=[]
    for ref in free:
        current=positions.get(ref)
        if current is None:continue
        edges=neighbors.get(ref,[])
        if not edges:continue
        sw=sum(w for _,w in edges)
        target=(sum(positions[o][0]*w for o,w in edges)/sw,
                sum(positions[o][1]*w for o,w in edges)/sw)
        anchor_neighbors=sorted(o for o,_ in edges if o in fixed)
        rotations=ROTATIONS if authority.get("optimization",{}).get("allow_rotation",True) else [orientations[ref]]
        sides=LAYERS if authority.get("optimization",{}).get("allow_top_bottom",True) else [layers[ref]]
        options=[]
        for rot in rotations:
            for side in sides:
                delta=rot-orientations[ref]
                box=shifted_box(envelopes.get(ref),current,target,delta)
                collision=False
                for other,other_box in envelopes.items():
                    if other==ref or other_box is None:continue
                    if overlap(box,other_box):collision=True;break
                options.append({
                    "target_mils":[round(target[0],3),round(target[1],3)],
                    "rotation":rot,"layer":side,
                    "status":"CANDIDATE" if not collision else "REJECTED_COLLISION",
                    "anchor_neighbors":anchor_neighbors,
                    "collision":collision
                })
        candidates.append({
            "reference":ref,"current_mils":current,"current_rotation":orientations[ref],
            "current_layer":layers[ref],"anchor_neighbors":anchor_neighbors,
            "basis":"net-derived weighted component affinity; fixed anchors are reference-only",
            "options":options
        })

    result={
        "schema":"altium-placement-plan.v2","status":"PLANNED",
        "mode":authority.get("mode","GENERIC"),
        "authority_schema":authority["schema"],
        "fixed_anchors":fixed,"free_components":free,
        "fixed_anchor_snapshot":fixed_snapshot,
        "candidate_count":len(candidates),"candidates":candidates,
        "hard_constraints":{
            "fixed_position":True,"fixed_orientation":True,"fixed_layer":True,
            "fixed_mechanical_envelope":True,"fixed_anchors_may_not_move":True
        },
        "optimization_order":[
            "FIXED_ANCHORS","DERIVE_FUNCTIONAL_ZONES","PLACE_FREE_COMPONENTS",
            "OPTIMIZE_ROTATION","OPTIMIZE_TOP_BOTTOM","CHECK_CLEARANCE",
            "CHECK_ASSEMBLY","VERIFY_ROUTING_FEASIBILITY"
        ],
        "mutation":"FORBIDDEN",
        "next_stage":"PLACEMENT_LEGALITY_AND_OBJECTIVE_EVALUATION"
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
