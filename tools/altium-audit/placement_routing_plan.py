#!/usr/bin/env python3
"""Evidence-first placement/routing planner. Planning only; never mutates a PCB."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from collections import defaultdict
from altium_monkey import AltiumPcbDoc
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
    pts=[]
    for pad in list(getattr(pcb,"pads",[]) or []):
        ci=f(pad,"component_index")
        try:
            if ci is None or int(ci)!=comp_index: continue
        except Exception:
            continue
        q=xy(pad)
        w=num(f(pad,"width_mils","width")); h=num(f(pad,"height_mils","height"))
        if q and w and h:
            pts.append((q[0]-w/2,q[1]-h/2,q[0]+w/2,q[1]+h/2))
    if not pts:return None
    return (min(x[0] for x in pts),min(x[1] for x in pts),
            max(x[2] for x in pts),max(x[3] for x in pts))

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
    ap=argparse.ArgumentParser(); ap.add_argument("--pcb",required=True,type=Path); ap.add_argument("--out",required=True,type=Path); ap.add_argument("--findings",type=Path); a=ap.parse_args()
    pcb=AltiumPcbDoc.from_file(a.pcb); comps=list(getattr(pcb,"components",[]) or []); nets=list(getattr(pcb,"nets",[]) or [])
    verified_topology_fail_nets=set()
    if a.findings and a.findings.exists():
        raw=json.loads(a.findings.read_text(encoding="utf-8"))
        fs=raw if isinstance(raw,list) else raw.get("findings",[])
        for finding in fs:
            if finding.get("id","").startswith("G7-TOPOLOGY-") and finding.get("status")=="FAIL" and finding.get("object") is not None:
                verified_topology_fail_nets.add(str(finding["object"]))
    placement=[]
    envelopes={}
    outline=getattr(getattr(pcb,"board",None),"outline",None)
    bb=getattr(outline,"bounding_box",None) if outline else None
    board_box=tuple(float(x) for x in bb) if bb and len(bb)==4 else None
    for i,c in enumerate(comps):
        ref=f(c,"designator","refdes","reference")
        pos,source=component_center(pcb,c)
        env=component_envelope(pcb,i)
        if ref is not None and env is not None: envelopes[str(ref)]=env
        inside=bool(pos is not None and (board_box is None or (board_box[0]<=pos[0]<=board_box[2] and board_box[1]<=pos[1]<=board_box[3])))
        placement.append({"component_index":i,"reference":str(ref) if ref is not None else None,"position":pos,
                          "evidence_source":source,"inside_board":inside,
                          "placement_status":"VERIFIED" if pos is not None and source in ("authoritative_pick_place","authoritative_component_position") and inside else "UNKNOWN"})
    overlap_pairs=[]
    refs=sorted(envelopes)
    for i,ra in enumerate(refs):
        for rb in refs[i+1:]:
            if boxes_overlap(envelopes[ra],envelopes[rb]): overlap_pairs.append((ra,rb))
    placement_checks={"all_positions_authoritative":all(x["placement_status"]=="VERIFIED" for x in placement),
                      "board_bounds_available":board_box is not None,"component_envelope_count":len(envelopes),
                      "overlap_count":len(overlap_pairs),"overlap_pairs":overlap_pairs[:200]}
    placement_status="VERIFIED" if placement_checks["all_positions_authoritative"] and placement_checks["board_bounds_available"] else "UNKNOWN"
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
        if cc>1:
            pads=data.get("pads",[]) or []
            routing.append({"net":str(name),"status":"TOPOLOGY_UNRESOLVED","graph_components":cc,"node_count":node_count,
                            "endpoints":[{"xy":xy(p),"designator":f(p,"designator","pad_designator","number")} for p in pads if xy(p) is not None],
                            "placement_dependency":"REVIEW","candidate_topology":"NOT_SELECTED",
                            "reason":"Disconnected copper is evidence only; no authoritative topology decision permits automatic bridging."})
        else:routing.append({"net":str(name),"status":"CONNECTED","graph_components":cc,"node_count":node_count})
    routing_status="UNKNOWN" if unresolved else ("INCOMPLETE" if any(x["status"]=="TOPOLOGY_UNRESOLVED" for x in routing) else "VERIFIED")
    result={"schema":"altium-placement-routing-plan.v3","mode":"PLAN_ONLY_NO_MUTATION",
            "status_semantics":{"VERIFIED":"authoritative evidence supports the claim","UNKNOWN":"evidence unavailable or fallback-only","INCOMPLETE":"known evidence exists but required closure is missing","BLOCKED":"policy prevents the next mutation stage"},
            "placement":{"status":placement_status,"components":placement,"checks":placement_checks,"lock":placement_lock},
            "routing":{"status":routing_status,"nets":routing,"unresolved_nets":unresolved},
            "design_status":"PASS" if placement_status=="VERIFIED" and routing_status=="VERIFIED" else "BLOCKED",
            "next_stage":"ROUTE_AND_VERIFY" if placement_status=="VERIFIED" and routing_status=="VERIFIED" else ("ROUTING_REPAIR" if placement_status=="VERIFIED" and routing_status=="INCOMPLETE" else "PLACEMENT_REVIEW")}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)); print(json.dumps({"placement_status":placement_status,"placement_lock":placement_lock["status"],"routing_status":routing_status,"unresolved_topologies":sum(x["status"]=="TOPOLOGY_UNRESOLVED" for x in routing),"parser_unresolved":len(unresolved)}))
    return 0 if result["design_status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
