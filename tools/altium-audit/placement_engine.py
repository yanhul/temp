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

def pcb_coord(v):
    """Normalize low-level Altium PCB internal units to public mil coordinates."""
    x=float(v)
    # altium-monkey exposes low-level PCB record coordinates in internal units;
    # its public PCB geometry is mil-based (10000 internal units per mil).
    return x/10000.0 if abs(x) >= 100000.0 else x

def pcb_box(bb):
    if not isinstance(bb,(list,tuple)) or len(bb)<4:return None
    try:return tuple(pcb_coord(x) for x in bb[:4])
    except Exception:return None

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
                try:found.append(pcb_box(bb))
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



def board_bounds(pcb):
    """Return authoritative board outline bbox, or None (fail closed)."""
    board=getattr(pcb,"board",None)
    outline=get(board,"outline") if board is not None else None
    bb=get(outline,"bounding_box","bbox","bounds") if outline is not None else None
    if isinstance(bb,(list,tuple)) and len(bb)>=4:
        try:return tuple(float(x) for x in bb[:4])
        except Exception:pass
    return None

def collect_keepouts(pcb):
    out=[]
    for name in ("keepouts","keepout_regions","keepout_areas","regions","shapebased_regions"):
        try:items=list(getattr(pcb,name,[]) or [])
        except Exception:continue
        for obj in items:
            layer_name=str(get(obj,"layer_name","layer","mechanical_layer") or "").upper()
            kind=str(get(obj,"kind","type","region_type","name") or "").upper()
            if name not in ("keepouts","keepout_regions","keepout_areas") and "KEEP" not in (layer_name+" "+kind):
                continue
            bb=get(obj,"bounding_box","bbox","bounds")
            if isinstance(bb,(list,tuple)) and len(bb)>=4:
                try:out.append(pcb_box(bb))
                except Exception:pass
    return out

def component_geometry_points(pcb,i):
    comps=list(getattr(pcb,"components",[]) or [])
    if i>=len(comps):return []
    c=comps[i]; ref=str(get(c,"designator","refdes","reference") or "")
    points=[]
    for name in ("component_bodies","shapebased_component_bodies","regions","shapebased_regions"):
        try:items=list(getattr(pcb,name,[]) or [])
        except Exception:continue
        for body in items:
            owner=get(body,"component","component_index","owner","designator","refdes","reference")
            if owner is not None and str(owner) not in {str(i),ref}:continue
            lname=str(get(body,"layer_name","layer","mechanical_layer") or "").upper()
            if name in ("regions","shapebased_regions") and "COURTYARD" not in lname:continue
            for attr in ("vertices","points","outline","contours"):
                vals=get(body,attr)
                try: vals=list(vals) if vals is not None else []
                except Exception: vals=[]
                for p in vals:
                    q=xy(p)
                    if q is not None:points.append((pcb_coord(q[0]),pcb_coord(q[1])))
            if not points:
                bb=get(body,"bounding_box","bbox","bounds")
                if isinstance(bb,(list,tuple)) and len(bb)>=4:
                    try:
                        x0,y0,x1,y1=pcb_box(bb)
                        points.extend(((x0,y0),(x1,y0),(x1,y1),(x0,y1)))
                    except Exception:pass
    if not points:
        # If component-body vertices are unavailable, reuse the same
        # authoritative component envelope used by placement legality.
        # This is conservative collision geometry; it does not authorize
        # rotation because the exact footprint outline is still unknown.
        env=envelope(pcb,i)
        if env is not None:
            x0,y0,x1,y1=env
            points=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
    if not points:
        # Same authoritative PcbDoc footprint fallback used by audit_runner.
        # This prevents placement from declaring geometry unavailable merely
        # because component-body vertices are not exposed by the parser.
        try:
            fp_lib=pcb.extract_footprint(get(c,"footprint"))
            fp=list(getattr(fp_lib,"footprints",[]) or [None])[0]
            local=[]
            for attr in ("pads","tracks","arcs","regions","component_bodies"):
                for obj in list(getattr(fp,attr,[]) or []):
                    q=xy(obj)
                    if q is not None: local.append(q)
            p=center(pcb,c)
            if local and p:
                try: rot=math.radians(orientation(c))
                except Exception: rot=0.0
                co,si=math.cos(rot),math.sin(rot)
                points=[(p[0]+lx*co-ly*si,p[1]+lx*si+ly*co) for lx,ly in local]
        except Exception:
            pass
    return points

def transform_points(points,old,new,delta):
    if not points:return []
    rad=math.radians(delta); co,si=math.cos(rad),math.sin(rad)
    cx=sum(p[0] for p in points)/len(points); cy=sum(p[1] for p in points)/len(points)
    return [(new[0]+(p[0]-cx)*co-(p[1]-cy)*si,
             new[1]+(p[0]-cx)*si+(p[1]-cy)*co) for p in points]

def points_bbox(points):
    if not points:return None
    xs=[p[0] for p in points]; ys=[p[1] for p in points]
    return (min(xs),min(ys),max(xs),max(ys))

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
    positions={}; orientations={}; layers={}; envelopes={}; geometry={}; geometry_exact={}
    for i,c in enumerate(comps):
        ref=get(c,"designator","refdes","reference")
        if ref is None:continue
        ref=str(ref); positions[ref]=center(pcb,c); orientations[ref]=orientation(c); layers[ref]=layer(c); envelopes[ref]=envelope(pcb,i)
        geometry[ref]=component_geometry_points(pcb,i)
        # Explicit vertices/outlines are exact geometry evidence; a bbox fallback
        # is usable for collision prechecks but is NOT sufficient to authorize rotation.
        geometry_exact[ref]=False
        for name in ("component_bodies","shapebased_component_bodies","regions","shapebased_regions"):
            try: items=list(getattr(pcb,name,[]) or [])
            except Exception: continue
            for body in items:
                owner=get(body,"component","component_index","owner","designator","refdes","reference")
                if owner is not None and str(owner) not in {str(i),ref}: continue
                lname=str(get(body,"layer_name","layer","mechanical_layer") or "").upper()
                if name in ("regions","shapebased_regions") and "COURTYARD" not in lname: continue
                if any(get(body,a) is not None for a in ("vertices","points","outline","contours")):
                    geometry_exact[ref]=True
                    break
            if geometry_exact[ref]: break
    board_box=board_bounds(pcb)
    keepouts=collect_keepouts(pcb)
    if board_box is None:
        result={"schema":"altium-placement-plan.v2","status":"BLOCKED","mode":authority.get("mode"),"reason":"board outline unavailable; placement bounds cannot be verified"}
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8"); return 1

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
        # Keep the affinity-derived target inside the authoritative board search
        # domain. This is a geometric solver constraint, not design intent.
        pts=geometry.get(ref,[])
        if pts and board_box:
            cb=points_bbox(pts)
            if cb:
                hw=abs(cb[2]-cb[0])/2.0; hh=abs(cb[3]-cb[1])/2.0
                target=(min(max(target[0],board_box[0]+hw),board_box[2]-hw),
                        min(max(target[1],board_box[1]+hh),board_box[3]-hh))
        anchor_neighbors=sorted({o for o,_,_ in evidence if o in fixed})
        basis_counts=defaultdict(int)
        for _,_,basis in evidence: basis_counts[basis]+=1

        rotations=ROTATIONS if authority.get("optimization",{}).get("allow_rotation",True) else [orientations[ref]]
        sides=LAYERS if authority.get("optimization",{}).get("allow_top_bottom",True) else [layers[ref]]
        options=[]
        cb=points_bbox(geometry.get(ref,[])) if geometry.get(ref) else None
        step=max(abs(cb[2]-cb[0]) if cb else 0.0, abs(cb[3]-cb[1]) if cb else 0.0, 100.0)
        # Deterministic local-to-regional search: expand in envelope-sized
        # increments so dense existing placement does not dead-end the solver.
        offsets=[(x,y) for radius in range(0,4) for x in range(-radius,radius+1)
                 for y in range(-radius,radius+1)
                 if max(abs(x),abs(y))==radius]
        search_targets=[]
        for ox,oy in offsets:
            tx=target[0]+ox*step; ty=target[1]+oy*step
            if cb and board_box:
                hw=abs(cb[2]-cb[0])/2.0; hh=abs(cb[3]-cb[1])/2.0
                tx=min(max(tx,board_box[0]+hw),board_box[2]-hw)
                ty=min(max(ty,board_box[1]+hh),board_box[3]-hh)
            p=(round(tx,3),round(ty,3))
            if p not in search_targets: search_targets.append(p)
        for candidate_target in search_targets:
            for rot in rotations:
                for side in sides:
                    delta=rot-orientations[ref]
                    rejection=[]
                    points=geometry.get(ref,[])
                    if not points:
                        rejection.append({"reason":"COMPONENT_GEOMETRY_UNAVAILABLE"})
                        box=None
                    else:
                        moved_points=transform_points(points,current,candidate_target,delta)
                        box=points_bbox(moved_points)
                        if box[0] < board_box[0] or box[1] < board_box[1] or box[2] > board_box[2] or box[3] > board_box[3]:
                            rejection.append({"reason":"BOARD_BOUNDS"})
                        for ko in keepouts:
                            if overlap(box,ko):
                                rejection.append({"reason":"KEEPOUT_OVERLAP"})
                        for other,other_box in envelopes.items():
                            if other==ref or other_box is None:
                                continue
                            if side==layers.get(other) and overlap(box,other_box):
                                rejection.append({"reason":"COMPONENT_COURTYARD_OVERLAP","other":other})
                        if delta % 360 != 0 and not geometry_exact.get(ref,False):
                            rejection.append({"reason":"ROTATION_GEOMETRY_UNAVAILABLE"})
                    distance=((candidate_target[0]-current[0])**2+(candidate_target[1]-current[1])**2)**0.5
                    options.append({
                        "target_mils":[round(candidate_target[0],3),round(candidate_target[1],3)],
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

    reserved=[]; placement_order=[]; reservation_failures=[]
    ordered=sorted(candidates,key=lambda x:(-len(x["anchor_neighbors"]),x["reference"]))
    for item in ordered:
        ref=item["reference"]; current=item["current_mils"]
        ranked=sorted(
            [o for o in item["options"] if o["status"] in {"CANDIDATE","RESERVED_CANDIDATE"}],
            key=lambda o: (
                o["objective"]["target_distance_mils"],
                0 if o["layer"]==item["current_layer"] else 1,
                0 if o["rotation"]==item["current_rotation"] else 1,
                ROTATIONS.index(o["rotation"]), LAYERS.index(o["layer"])
            )
        )
        chosen=None
        rejected=[]
        for sel in ranked:
            delta=sel["rotation"]-item["current_rotation"]; pts=geometry.get(ref,[])
            moved=transform_points(pts,current,tuple(sel["target_mils"]),delta) if pts else []
            box=points_bbox(moved)
            conflicts=[]
            if box is not None:
                for r,rb,rl in reserved:
                    if sel["layer"]==rl and rb is not None and overlap(box,rb): conflicts.append(r)
            if conflicts:
                rejected.append({"candidate":sel["target_mils"],"rotation":sel["rotation"],"layer":sel["layer"],"others":conflicts})
                continue
            chosen=(sel,box); break
        if chosen is None:
            reservation_failures.append({"reference":ref,"reason":"NO_CANDIDATE_SURVIVES_GLOBAL_RESERVATION","rejected_candidates":rejected})
            continue
        sel,box=chosen
        item["selected"]=sel
        sel["status"]="RESERVED_CANDIDATE"
        sel.setdefault("global_rejections",[]).extend(rejected)
        reserved.append((ref,box,sel["layer"]))
        placement_order.append(ref)
    if reservation_failures:
        result={"schema":"altium-placement-plan.v2","status":"BLOCKED","mode":authority.get("mode"),"reason":"global placement reservation failed","reservation_failures":reservation_failures,"candidate_count":len(candidates),"placement_order":placement_order}
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8"); return 1
    final_conflicts=[]
    for i,(ra,ba,la) in enumerate(reserved):
        for rb,bb,lb in reserved[i+1:]:
            if la==lb and ba is not None and bb is not None and overlap(ba,bb):
                final_conflicts.append((ra,rb))
    if final_conflicts:
        result={"schema":"altium-placement-plan.v2","status":"BLOCKED","mode":authority.get("mode"),"reason":"final global placement recheck failed","conflicts":final_conflicts}
        Path(out_path).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8"); return 1

    result={
        "schema":"altium-placement-plan.v2","status":"PLANNED",
        "mode":authority.get("mode","GENERIC"),
        "authority_schema":authority["schema"],
        "fixed_anchors":fixed,"free_components":free,
        "fixed_anchor_snapshot":fixed_snapshot,
        "candidate_count":len(candidates),"candidates":candidates,
        "board_bounds":board_box,"keepout_count":len(keepouts),
        "geometry_exact_count":sum(1 for v in geometry_exact.values() if v),
        "global_reservation":{"status":"VERIFIED","reserved_count":len(reserved),"placement_order":placement_order,"final_recheck":"VERIFIED"},
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
            "fixed_layer_only_if_authority_declares":True,"board_bounds":True,
            "keepout":True,"courtyard":True,"global_collision_reservation":True,
            "rotation_requires_explicit_geometry":True
        },
        "optimization_order":[
            "FIXED_ANCHORS","DERIVE_FUNCTIONAL_ZONES","GENERATE_CANDIDATES",
            "PLACE_WITH_GLOBAL_RESERVATION","OPTIMIZE_ROTATION","OPTIMIZE_TOP_BOTTOM",
            "CHECK_BOARD_BOUNDS","CHECK_KEEPOUT","CHECK_COURTYARD","CHECK_ASSEMBLY",
            "FINAL_GLOBAL_RECHECK",
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
