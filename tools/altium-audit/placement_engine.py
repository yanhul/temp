#!/usr/bin/env python3
"""Generic anchor-first placement planner.

Two execution profiles are supported:
- generic: all fixed/optimizable decisions come from an authority packet.
- workload-specific: fixed anchors and functional zones come only from an authority packet.

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

    # Assembly-access authority is a hard planning input. A normative baseline
    # is sufficient for generic planning checks, but it does not imply a
    # project/fabricator-specific industrial PASS.
    assembly=authority.get("assembly_access")
    if not isinstance(assembly,dict) or assembly.get("status") not in {"BASELINE_VERIFIED","VERIFIED"}:
        result={
            "schema":"altium-placement-plan.v2",
            "status":"BLOCKED",
            "mode":authority.get("mode"),
            "reason":"placement input sufficiency failed",
            "blocked_input":"assembly_access",
            "required":"BASELINE_VERIFIED or VERIFIED assembly-access authority"
        }
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        return 1

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

    # Functional zones are authority data, not algorithmic design knowledge.
    # The engine consumes them generically: zone member -> fixed/known zone anchors.
    zones=authority.get("functional_zones",{}) or {}
    zone_anchors=defaultdict(list)
    for anchor,members in zones.items():
        if anchor not in positions:
            continue
        for member in members or []:
            zone_anchors[str(member)].append(str(anchor))

    candidates=[]
    blocked_refs=[]
    for ref in free:
        current=positions.get(ref)
        if current is None:
            blocked_refs.append({"reference":ref,"reason":"POSITION_MISSING"})
            continue

        edges=neighbors.get(ref,[])
        zanchors=[a for a in zone_anchors.get(ref,[]) if a in positions]
        evidence=[]
        # Connectivity is stronger evidence than a zone declaration; the zone
        # contributes a bounded prior so placement remains useful when affinity
        # is sparse, but never invents a target for a component with no authority.
        for other,w in edges:
            evidence.append((other,float(w),"NET_AFFINITY"))
        for anchor in zanchors:
            evidence.append((anchor,1.0,"FUNCTIONAL_ZONE"))

        if not evidence:
            blocked_refs.append({
                "reference":ref,
                "reason":"NO_PLACEMENT_TARGET_EVIDENCE",
                "required":"net_connectivity_or_functional_zone_authority"
            })
            continue

        # Weighted target derived solely from observed component positions and
        # authority-declared zone membership.
        sw=sum(w for _,w,_ in evidence)
        target=(sum(positions[o][0]*w for o,w,_ in evidence)/sw,
                sum(positions[o][1]*w for o,w,_ in evidence)/sw)
        anchor_neighbors=sorted({o for o,_,_ in evidence if o in fixed})
        basis_counts=defaultdict(int)
        for _,_,basis in evidence: basis_counts[basis]+=1

        rotations=ROTATIONS if authority.get("optimization",{}).get("allow_rotation",True) else [orientations[ref]]
        sides=LAYERS if authority.get("optimization",{}).get("allow_top_bottom",True) else [layers[ref]]
        options=[]
        for rot in rotations:
            for side in sides:
                delta=rot-orientations[ref]
                box=shifted_box(envelopes.get(ref),current,target,delta)
                rejection=[]
                for other,other_box in envelopes.items():
                    if other==ref or other_box is None:
                        continue
                    # 2-D component/courtyard collision is only authoritative
                    # on the same assembly side. Do not invent cross-side 3-D
                    # interference without mechanical authority.
                    if side==layers.get(other) and overlap(box,other_box):
                        rejection.append({
                            "reason":"COMPONENT_ENVELOPE_OVERLAP",
                            "other":other
                        })
                distance=((target[0]-current[0])**2+(target[1]-current[1])**2)**0.5
                options.append({
                    "target_mils":[round(target[0],3),round(target[1],3)],
                    "rotation":rot,"layer":side,
                    "status":"CANDIDATE" if not rejection else "REJECTED_COLLISION",
                    "anchor_neighbors":anchor_neighbors,
                    "collision":bool(rejection),
                    "rejections":rejection,
                    "objective":{"target_distance_mils":round(distance,3)}
                })

        legal=[o for o in options if o["status"]=="CANDIDATE"]
        if not legal:
            blocked_refs.append({
                "reference":ref,
                "reason":"NO_LEGAL_PLACEMENT_CANDIDATE",
                "rejections":[o["rejections"] for o in options]
            })
            continue

        # Deterministic selection only; no PcbDoc mutation occurs here.
        selected=min(legal, key=lambda o: (
            o["objective"]["target_distance_mils"],
            0 if o["layer"]==layers[ref] else 1,
            0 if o["rotation"]==orientations[ref] else 1,
            ROTATIONS.index(o["rotation"]),
            LAYERS.index(o["layer"])
        ))

        candidates.append({
            "reference":ref,"current_mils":current,"current_rotation":orientations[ref],
            "current_layer":layers[ref],"anchor_neighbors":anchor_neighbors,
            "zone_anchors":zanchors,
            "basis":{"evidence_counts":dict(basis_counts),
                     "rule":"weighted target from authority zones + observed net affinity"},
            "selected":selected,"options":options
        })
    if blocked_refs:
        result={
            "schema":"altium-placement-plan.v2","status":"BLOCKED",
            "mode":authority.get("mode"),"reason":"placement input sufficiency failed",
            "blocked_components":blocked_refs,
            "fixed_anchors":fixed
        }
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        return 1

    result={
        "schema":"altium-placement-plan.v2","status":"PLANNED",
        "mode":authority.get("mode","GENERIC"),
        "authority_schema":authority["schema"],
        "fixed_anchors":fixed,"free_components":free,
        "fixed_anchor_snapshot":fixed_snapshot,
        "candidate_count":len(candidates),"candidates":candidates,
        "functional_zone_count":len(zones),
        "target_evidence":"NET_AFFINITY and/or authority FUNCTIONAL_ZONE; no target may be guessed",
        "assembly_access_authority":{
            "status":assembly.get("status"),
            "scope":assembly.get("scope"),
            "project_specific_fabricator_process":(assembly.get("project_specific_fabricator_process") or {}).get("status")
        },
        "hard_constraints":{
            "fixed_position":True,"fixed_orientation":True,
            "fixed_mechanical_envelope":True,"fixed_anchors_may_not_move":True,
            "fixed_layer_only_if_authority_declares":True
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
