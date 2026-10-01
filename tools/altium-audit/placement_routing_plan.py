#!/usr/bin/env python3
"""Evidence-first placement/routing planner. Planning only; never mutates a PCB."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from collections import defaultdict
from altium_monkey import AltiumPcbDoc
from industrial_rules import evaluate as evaluate_industrial_rules
from placement_optimizer import PlacementConfig, PlacementNode, optimize as optimize_placement
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

def _scalar_xy(o):
    q = xy(o)
    return [q] if q is not None else []


def _geometry_points(obj):
    """Extract geometry points only from the supplied body/region object."""
    points = []
    for attr in ("bounding_box", "bbox", "bounds"):
        bb = f(obj, attr)
        if isinstance(bb, (tuple, list)) and len(bb) >= 4:
            vals = [num(x) for x in bb[:4]]
            if all(x is not None for x in vals):
                x0, y0, x1, y1 = vals
                points.extend(((x0, y0), (x1, y1)))
                return points
    for attr in ("vertices", "points", "outline", "contours", "primitives", "geometry"):
        try:
            value = getattr(obj, attr)
            if callable(value):
                value = value()
        except Exception:
            continue
        if value is None:
            continue
        try:
            items = list(value)
        except Exception:
            continue
        for item in items:
            points.extend(_geometry_points(item))
            q = xy(item)
            if q is not None:
                points.append(q)
            e = endpoint(item)
            if e is not None:
                points.extend(e)
    return points


def _body_owner(body):
    """Return explicit parser ownership metadata; never infer from coordinates."""
    for key in (
        "component", "component_index", "owner", "owner_component",
        "parent_component", "designator", "refdes", "reference"
    ):
        value = f(body, key)
        if value is not None:
            return value
    return None


def _owner_matches(owner, comp, comp_index, ref):
    if owner is None:
        return False
    if owner is comp:
        return True
    if isinstance(owner, int) and owner == comp_index:
        return True
    if str(owner) == str(comp_index):
        return True
    if ref is not None and str(owner) == str(ref):
        return True
    for key in ("designator", "refdes", "reference", "name"):
        value = f(owner, key)
        if value is not None and ref is not None and str(value) == str(ref):
            return True
    return False


def component_envelope(pcb, comp_index):
    """Return an authoritative body/courtyard envelope or fail closed.

    Copper pads/tracks are deliberately excluded: they cannot prove the
    component body or courtyard envelope required for placement legality.
    """
    comps = list(getattr(pcb, "components", []) or [])
    if comp_index >= len(comps):
        return None, "UNAVAILABLE"
    comp = comps[comp_index]
    ref = f(comp, "designator", "refdes", "reference")

    collections = (
        ("component_bodies", "COMPONENT_BODY_GEOMETRY"),
        ("shapebased_component_bodies", "COMPONENT_BODY_GEOMETRY"),
        ("regions", "COURTYARD_GEOMETRY"),
        ("shapebased_regions", "COURTYARD_GEOMETRY"),
    )
    found = []
    for collection_name, source in collections:
        try:
            collection = list(getattr(pcb, collection_name, []) or [])
        except Exception:
            continue
        for body in collection:
            layer = f(body, "layer", "layer_id", "mechanical_layer", "mechanical_layer_id")
            layer_name = str(f(body, "layer_name", "layer") or "").upper()
            semantic_courtyard = "COURTYARD" in layer_name
            if collection_name in ("regions", "shapebased_regions") and not semantic_courtyard:
                continue
            owner = _body_owner(body)
            if owner is not None and not _owner_matches(owner, comp, comp_index, ref):
                continue
            points = _geometry_points(body)
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                found.append((
                    min(xs), min(ys), max(xs), max(ys),
                    "COURTYARD_GEOMETRY" if semantic_courtyard else source,
                    layer,
                ))
    if not found:
        return None, "UNAVAILABLE"
    # Prefer semantic courtyard geometry when present; otherwise use an
    # explicitly component-owned body envelope. No copper fallback.
    found.sort(key=lambda x: x[4] != "COURTYARD_GEOMETRY")
    env = found[0]
    return env[:4], env[4]

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
                      "overlap_count":len(overlap_pairs),"overlap_pairs":overlap_pairs[:200],"overlap_evidence":"authoritative_component_body_or_courtyard_geometry" if envelopes else "UNAVAILABLE",
                      "envelope_sources":dict(sorted({x["reference"]:x.get("envelope_source") for x in placement if x.get("reference") and x.get("envelope_source")!="UNAVAILABLE"}.items()))}
    # Generic placement optimization: derive candidates from compiled-net affinity,
    # authoritative envelopes and board bounds. Never mutate the PcbDoc here.
    pos_by_ref={x["reference"]:x["position"] for x in placement if x.get("reference") and x.get("position") is not None}
    placement_rules=(industrial.get("rules",{}) if isinstance(industrial,dict) else {})
    placement_rule_keys=("component_clearance","board_edge_clearance","courtyard","keepout","assembly_access")
    placement_authority=all(isinstance(placement_rules.get(k),dict) and placement_rules[k].get("status") in ("APPLICABLE","NOT_APPLICABLE") for k in placement_rule_keys)
    affinity_map={tuple(sorted((str(a),str(b)))):float(w) for (a,b),w in affinity_by_pair.items() if a in pos_by_ref and b in pos_by_ref}
    optimizer_result={"schema":"altium-placement-optimizer.v1","status":"BLOCKED","reason":"optimizer prerequisites unavailable","mutation":"FORBIDDEN"}
    if board_box is not None and envelopes and placement_authority:
        nodes=[]
        for ref,pos in pos_by_ref.items():
            env=envelopes.get(ref)
            if env is not None:
                nodes.append(PlacementNode(ref,tuple(pos),tuple(env),ref in locked_refs))
        if nodes:
            optimizer_result=optimize_placement(nodes,affinity_map,board_box,PlacementConfig(edge_clearance_mils=0.0))
    optimizer_moves=optimizer_result.get("moves",[]) if isinstance(optimizer_result,dict) else []
    candidate_moves=[m for m in optimizer_moves if m.get("changed")]
    for m in candidate_moves:
        m["basis"]="generic weighted connectivity-affinity coordinate descent"
        m["authority"]="compiled-netlist affinity + authoritative geometry/rules"
        m["status"]="LEGAL_CANDIDATE" if optimizer_result.get("status")=="OPTIMIZED" else "PENDING_VERIFICATION"
    placement_quality={
        "schema":"altium-placement-affinity.v3",
        "status":optimizer_result.get("status","BLOCKED"),
        "basis":"generic deterministic optimizer over compiled-netlist affinity + authoritative component geometry",
        "candidate_moves":candidate_moves[:500],
        "optimizer":optimizer_result,
        "mutation":"FORBIDDEN_IN_THIS_STAGE",
        "locked_references":sorted(locked_refs),
        "legal_candidate_count":sum(x.get("status")=="LEGAL_CANDIDATE" for x in candidate_moves),
        "next_action":"APPLY_AND_VERIFY_PLACEMENT" if optimizer_result.get("status")=="OPTIMIZED" else "PLACEMENT_REVIEW",
    }
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
