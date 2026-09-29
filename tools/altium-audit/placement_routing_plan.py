#!/usr/bin/env python3
"""Evidence-first placement/routing planner. Planning only; never mutates a PCB."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from collections import defaultdict
from altium_monkey import AltiumPcbDoc
from industrial_rules import evaluate as evaluate_industrial_rules
def f(o,*ks):
    if isinstance(o,dict):
        for k in ks:
            if o.get(k) is not None:return o[k]
    for k in ks:
        try:
            v=getattr(o,k)
            if v is not None:return v
        except Exception:pass
    return None
def num(v):
    try:return float(v)
    except Exception:return None
def xy(o):
    for a,b in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x,y=f(o,a),f(o,b)
        if x is not None and y is not None:
            x,y=num(x),num(y)
            if x is not None and y is not None:return x,y
    p=f(o,"position","location","center")
    if p is not None:
        if isinstance(p,(tuple,list)) and len(p)>=2:
            x,y=num(p[0]),num(p[1])
            if x is not None and y is not None:return x,y
        x,y=f(p,"x","X"),f(p,"y","Y")
        if x is not None and y is not None:return num(x),num(y)
    return None
def component_center(pcb, comp):
    try:
        q=pcb.get_component_pick_place_center_mils(comp)
        if q is not None:
            return (float(q[0]), float(q[1])), "authoritative_pick_place"
    except Exception:
        pass
    try:
        q=(float(comp.get_x_mils()),float(comp.get_y_mils()))
        return q, "authoritative_component_position"
    except Exception:
        pass
    q=xy(comp)
    if q is not None:
        return q, "component_geometry"
    return None, "unresolved"

def component_envelope(pcb, comp_index):
    comps=list(getattr(pcb,"components",[]) or [])
    if comp_index >= len(comps): return None, "UNAVAILABLE"
    comp=comps[comp_index]
    bb=f(comp,"bounding_box","bbox","bounds")
    if isinstance(bb,(tuple,list)) and len(bb)>=4:
        vals=[num(x) for x in bb[:4]]
        if all(x is not None for x in vals):
            x0,y0,x1,y1=vals
            return (min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1)), "COMPONENT_BBOX"
    ref=f(comp,"designator","refdes","reference")
    prims=None
    for arg in (comp,ref,comp_index):
        try:
            prims=pcb.get_component_primitives(arg)
            if prims is not None: break
        except Exception: pass
    points=[]
    for p in list(prims or []):
        q=xy(p)
        if q: points.append(q)
        e=endpoint(p)
        if e: points.extend(e)
    if points:
        return (min(x for x,y in points),min(y for x,y in points),
                max(x for x,y in points),max(y for x,y in points)), "COPPER_PRIMITIVES"
    return None, "UNAVAILABLE"

def boxes_overlap(a,b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

def endpoint(o):
    q=[num(f(o,k)) for k in ("x1","y1","x2","y2")]
    return ((q[0],q[1]),(q[2],q[3])) if all(x is not None for x in q) else None
def components_for_net(data):
    pads=[xy(x) for x in data.get("pads",[]) or [] if xy(x) is not None]; vias=[xy(x) for x in data.get("vias",[]) or [] if xy(x) is not None]
    routes=[z for o in list(data.get("tracks",[]) or [])+list(data.get("arcs",[]) or []) if (z:=endpoint(o))]
    nodes=pads+vias+[p for z in routes for p in z]
    if len(nodes)<2:return len(nodes),0
    parent=list(range(len(nodes)))
    def find(i):
        while parent[i]!=i: parent[i]=parent[parent[i]]; i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    buckets=defaultdict(list)
    for i,p in enumerate(nodes):buckets[(round(p[0]),round(p[1]))].append(i)
    for ids in buckets.values():
        for j in ids[1:]:union(ids[0],j)
    for a,b in routes:
        ia=next((i for i,p in enumerate(nodes) if p==a),None); ib=next((i for i,p in enumerate(nodes) if p==b),None)
        if ia is not None and ib is not None:union(ia,ib)
    def point_segment_distance(p,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]
        if dx==dy==0:return math.dist(p,a)
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
        q=(a[0]+t*dx,a[1]+t*dy)
        return math.dist(p,q)
    for i,p in enumerate(nodes):
        for a,b in routes:
            if p==a or p==b: continue
            if point_segment_distance(p,a,b)<=1.0:
                ia=next((j for j,x in enumerate(nodes) if x==a),None)
                ib=next((j for j,x in enumerate(nodes) if x==b),None)
                if ia is not None: union(i,ia)
                if ib is not None: union(i,ib)
    return len(nodes),len({find(i) for i in range(len(nodes))})
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--pcb",required=True,type=Path); ap.add_argument("--out",required=True,type=Path); ap.add_argument("--findings",type=Path); ap.add_argument("--config",type=Path); ap.add_argument("--connectivity-manifest",type=Path); a=ap.parse_args()
    pcb=AltiumPcbDoc.from_file(a.pcb); comps=list(getattr(pcb,"components",[]) or []); nets=list(getattr(pcb,"nets",[]) or [])
    industrial=evaluate_industrial_rules(a.config, pcb, (a.findings.parent / "g4_probe.json") if a.findings else None)
    geometry_probe=[]
    for collection_name in ("component_bodies","shapebased_component_bodies","regions","shapebased_regions"):
        try:
            coll=list(getattr(pcb,collection_name,[]) or [])
            for obj in coll[:5]:
                attrs=[]
                for name in dir(obj):
                    if name.startswith("_"): continue
                    try:
                        v=getattr(obj,name)
                        if callable(v):
                            attrs.append((name,"<callable>"))
                            continue
                        if isinstance(v,(str,int,float,bool,type(None))): attrs.append((name,v))
                    except Exception: pass
                geometry_probe.append({"collection":collection_name,"class":obj.__class__.__name__,"attrs":attrs[:80]})
        except Exception: pass
    verified_topology_fail_nets=set()
    if a.findings and a.findings.exists():
        raw=json.loads(a.findings.read_text(encoding="utf-8"))
        fs=raw if isinstance(raw,list) else raw.get("findings",[])
        for finding in fs:
            if finding.get("id","").startswith("G7-TOPOLOGY-") and finding.get("status")=="FAIL" and finding.get("object") is not None:
                verified_topology_fail_nets.add(str(finding["object"]))
    connectivity={}
    placement_config={}
    if a.config and a.config.exists():
        try:
            cfg=json.loads(a.config.read_text(encoding="utf-8-sig"))
            placement_config=cfg.get("placement",{}) if isinstance(cfg,dict) else {}
        except Exception:
            placement_config={}
    locked_refs=set(str(x) for x in placement_config.get("locked_references",[]) or [])
    if a.connectivity_manifest and a.connectivity_manifest.exists():
        try: connectivity=json.loads(a.connectivity_manifest.read_text(encoding="utf-8")).get("intelligence",{}) or {}
        except Exception: connectivity={}
    affinity_by_pair={}
    for item in connectivity.get("component_affinity",[]) or []:
        affinity_by_pair[tuple(sorted((str(item.get("a")),str(item.get("b")))))] = float(item.get("weight",0) or 0)
    placement=[]
    envelopes={}
    outline=getattr(getattr(pcb,"board",None),"outline",None)
    bb=getattr(outline,"bounding_box",None) if outline else None
    board_box=tuple(float(x) for x in bb) if bb and len(bb)==4 else None
    for i,c in enumerate(comps):
        ref=f(c,"designator","refdes","reference")
        pos,source=component_center(pcb,c)
        env,env_source=component_envelope(pcb,i)
        if ref is not None and env is not None: envelopes[str(ref)]=env
        inside=bool(pos is not None and (board_box is None or (board_box[0]<=pos[0]<=board_box[2] and board_box[1]<=pos[1]<=board_box[3])))
        placement.append({"component_index":i,"reference":str(ref) if ref is not None else None,"position":pos,
                          "evidence_source":source,"inside_board":inside,"envelope_source":env_source,
                          "placement_status":"VERIFIED" if pos is not None and source in ("authoritative_pick_place","authoritative_component_position") and inside else "UNKNOWN"})
    overlap_pairs=[]
    refs=sorted(envelopes)
    for i,ra in enumerate(refs):
        for rb in refs[i+1:]:
            if boxes_overlap(envelopes[ra],envelopes[rb]): overlap_pairs.append((ra,rb))
    placement_checks={"all_positions_authoritative":all(x["placement_status"]=="VERIFIED" for x in placement),
                      "board_bounds_available":board_box is not None,"component_envelope_count":len(envelopes),
                      "overlap_count":len(overlap_pairs),"overlap_pairs":overlap_pairs[:200],"overlap_evidence":"component_bbox_or_copper_primitives" if envelopes else "UNAVAILABLE",
                      "envelope_sources":dict(sorted({x["reference"]:x.get("envelope_source") for x in placement if x.get("reference") and x.get("envelope_source")!="UNAVAILABLE"}.items()))}
    # Connectivity-driven placement is advisory at this stage. It scores the
    # current placement against net-derived component affinity but does not
    # mutate coordinates or claim design intent.
    pos_by_ref={x["reference"]:x["position"] for x in placement if x.get("reference") and x.get("position") is not None}
    affinity_observed=[]
    affinity_missing=[]
    for (ra,rb), weight in sorted(affinity_by_pair.items(), key=lambda x:(-x[1],x[0])):
        pa,pb=pos_by_ref.get(ra),pos_by_ref.get(rb)
        rec={"a":ra,"b":rb,"weight":weight}
        if pa is not None and pb is not None:
            rec["distance_mils"]=round(math.dist(pa,pb),3); rec["status"]="OBSERVED"
            affinity_observed.append(rec)
        else:
            rec["status"]="UNRESOLVED"; affinity_missing.append(rec)
    # Produce candidate targets from the current graph only. This is a
    # recommendation surface; it is intentionally not a PCB mutation.
    neighbors=defaultdict(list)
    for pair in affinity_observed:
        w=max(float(pair.get("weight",0)),0.001)
        neighbors[pair["a"]].append((pair["b"],w))
        neighbors[pair["b"]].append((pair["a"],w))
    candidate_moves=[]
    for ref, edges in sorted(neighbors.items()):
        if len(edges) < 1 or ref not in pos_by_ref or ref in locked_refs: continue
        sx=sy=sw=0.0
        for other,w in edges:
            if other not in pos_by_ref: continue
            sx += pos_by_ref[other][0]*w
            sy += pos_by_ref[other][1]*w
            sw += w
        if sw <= 0: continue
        target=(round(sx/sw,3),round(sy/sw,3))
        current=pos_by_ref[ref]
        delta=round(math.dist(current,target),3)
        legal=True
        reasons=[]
        env_source = next((x.get("envelope_source") for x in placement if x.get("reference")==ref), "UNAVAILABLE")
        placement_rule_keys=("component_clearance","board_edge_clearance","courtyard","keepout","assembly_access")
        placement_rules=(industrial.get("rules",{}) if isinstance(industrial,dict) else {})
        placement_authority=all(isinstance(placement_rules.get(k),dict) and placement_rules[k].get("status") in ("APPLICABLE","NOT_APPLICABLE") for k in placement_rule_keys)
        if not placement_authority:
            legal=False
            reasons.append("PLACEMENT_RULE_AUTHORITY_INCOMPLETE")
        elif board_box is not None and ref in envelopes:
            env=envelopes[ref]
            dx,dy=target[0]-current[0],target[1]-current[1]
            moved=(env[0]+dx,env[1]+dy,env[2]+dx,env[3]+dy)
            if moved[0] < board_box[0] or moved[1] < board_box[1] or moved[2] > board_box[2] or moved[3] > board_box[3]:
                legal=False; reasons.append("BOARD_BOUNDS")
            if legal:
                for other,other_env in envelopes.items():
                    if other==ref: continue
                    if boxes_overlap(moved,other_env):
                        legal=False; reasons.append("COMPONENT_BBOX_OVERLAP"); break
        else:
            legal=False
            reasons.append("ENVELOPE_OR_BOARD_UNAVAILABLE")
        candidate_moves.append({
            "reference":ref,
            "current_mils":current,
            "suggested_target_mils":target,
            "move_distance_mils":delta,
            "basis":"weighted connectivity-affinity barycenter",
            "status":"LEGAL_CANDIDATE" if legal else ("PENDING_LEGALITY" if "PLACEMENT_RULE_AUTHORITY_INCOMPLETE" in reasons else "REJECTED_PRECHECK"),
            "precheck":reasons,
            "authority":"derived_from_compiled_netlist"
        })
    candidate_moves.sort(key=lambda x:(x["status"]!="LEGAL_CANDIDATE",-x["move_distance_mils"]))
    placement_quality={
        "schema":"altium-placement-affinity.v2",
        "status":"SUGGESTED" if connectivity.get("status")=="VERIFIED" else "UNKNOWN",
        "basis":"compiled-netlist component affinity + authoritative current component positions",
        "observed_pairs":affinity_observed[:500],
        "unresolved_pairs":affinity_missing[:500],
        "candidate_moves":candidate_moves[:500],
        "mutation":"FORBIDDEN_IN_THIS_STAGE",
        "locked_references":sorted(locked_refs),
        "legal_candidate_count":sum(x["status"]=="LEGAL_CANDIDATE" for x in candidate_moves),
        "pending_legality_count":sum(x["status"]=="PENDING_LEGALITY" for x in candidate_moves),
        "rejected_precheck_count":sum(x["status"]=="REJECTED_PRECHECK" for x in candidate_moves),
        "next_action":"OPTIMIZE_PLACEMENT" if any(x["status"]=="LEGAL_CANDIDATE" for x in candidate_moves) else "PLACEMENT_REVIEW"
    }
    placement_status="VERIFIED" if (placement_checks["all_positions_authoritative"] and placement_checks["board_bounds_available"] and placement_checks["overlap_count"]==0) else "BLOCKED"
    placement_lock={"schema":"altium-placement-lock.v1","status":"LOCKED" if placement_status=="VERIFIED" else "BLOCKED",
                    "basis":"authoritative component position + board bounds; pad-envelope overlap retained as diagnostic only because parser coordinate frame is not independently proven",
                    "checks":placement_checks,
                    "locked_references":sorted(x["reference"] for x in placement if x["placement_status"]=="VERIFIED")}
    routing=[]; unresolved=[]
    for i,n in enumerate(nets):
        name=f(n,"name","net_name","netname","uid")
        if name is None:continue
        try:data=pcb.get_net_primitives(i)
        except Exception:data=None
        if not isinstance(data,dict): unresolved.append(str(name)); continue
        node_count,cc=components_for_net(data)
        if cc>1 and str(name) in verified_topology_fail_nets:
            pads=data.get("pads",[]) or []
            routing.append({"net":str(name),"status":"TOPOLOGY_UNRESOLVED","graph_components":cc,"node_count":node_count,
                            "endpoints":[{"xy":xy(p),"designator":f(p,"designator","pad_designator","number")} for p in pads if xy(p) is not None],
                            "placement_dependency":"LOCKED","candidate_topology":"NOT_SELECTED",
                            "reason":"Disconnected copper is evidence only; no authoritative topology decision permits automatic bridging."})
        elif cc>1:
            routing.append({"net":str(name),"status":"OBSERVED_DISCONNECTED_UNCONFIRMED","graph_components":cc,"node_count":node_count,
                            "placement_dependency":"REVIEW","candidate_topology":"NOT_SELECTED",
                            "reason":"Geometry graph is disconnected but authoritative routing evidence did not classify it as a repairable failure."})
        else:routing.append({"net":str(name),"status":"CONNECTED","graph_components":cc,"node_count":node_count})
    # OBSERVED_DISCONNECTED_UNCONFIRMED is diagnostic only. It must not block closure
    # unless the authoritative audit evidence classified the net as a verified topology failure.
    routing_status=("UNKNOWN" if unresolved else ("INCOMPLETE" if any(x["status"]=="TOPOLOGY_UNRESOLVED" for x in routing) else "VERIFIED"))
    result={"schema":"altium-placement-routing-plan.v3","mode":"PLAN_ONLY_NO_MUTATION",
            "industrial_rule_authority":industrial,
            "geometry_probe":geometry_probe,
            "status_semantics":{"VERIFIED":"authoritative evidence supports the claim","UNKNOWN":"evidence unavailable or fallback-only","INCOMPLETE":"known evidence exists but required closure is missing","BLOCKED":"policy prevents the next mutation stage"},
            "placement":{"status":placement_status,"components":placement,"checks":placement_checks,"lock":placement_lock,"connectivity_intelligence":placement_quality},
            "routing":{"status":routing_status,"nets":routing,"unresolved_nets":unresolved},
            "design_status":"PASS" if placement_status=="VERIFIED" and routing_status=="VERIFIED" and industrial["status"]=="VERIFIED" else "BLOCKED",
            "next_stage":"ROUTE_AND_VERIFY" if placement_status=="VERIFIED" and routing_status=="VERIFIED" else ("ROUTING_REPAIR" if placement_status=="VERIFIED" and routing_status=="INCOMPLETE" else "PLACEMENT_REVIEW")}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)); print(json.dumps({"placement_status":placement_status,"placement_lock":placement_lock["status"],"routing_status":routing_status,"industrial_rules":industrial["status"],"unresolved_topologies":sum(x["status"]=="TOPOLOGY_UNRESOLVED" for x in routing),"parser_unresolved":len(unresolved)}))
    return 0 if result["design_status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
