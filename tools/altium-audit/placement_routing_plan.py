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
    return len(nodes),len({find(i) for i in range(len(nodes))})
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--pcb",required=True,type=Path); ap.add_argument("--out",required=True,type=Path); a=ap.parse_args()
    pcb=AltiumPcbDoc.from_file(a.pcb); comps=list(getattr(pcb,"components",[]) or []); nets=list(getattr(pcb,"nets",[]) or [])
    placement=[]
    for i,c in enumerate(comps):
        ref=f(c,"designator","refdes","reference"); p=xy(c); source="component_geometry"
        if p is None:
            pads=[xy(x) for x in list(f(c,"pads","children") or []) if xy(x) is not None]
            if pads:p=(sum(x for x,_ in pads)/len(pads),sum(y for _,y in pads)/len(pads)); source="pad_geometry_fallback"
        placement.append({"component_index":i,"reference":str(ref) if ref is not None else None,"position":p,"evidence_source":source,
                          "placement_status":"VERIFIED" if p is not None and source=="component_geometry" else "UNKNOWN"})
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
    pu=any(x["placement_status"]!="VERIFIED" for x in placement); placement_status="UNKNOWN" if pu else "VERIFIED"
    routing_status="UNKNOWN" if unresolved else ("INCOMPLETE" if any(x["status"]=="TOPOLOGY_UNRESOLVED" for x in routing) else "VERIFIED")
    result={"schema":"altium-placement-routing-plan.v2","mode":"PLAN_ONLY_NO_MUTATION",
            "status_semantics":{"VERIFIED":"authoritative evidence supports the claim","UNKNOWN":"evidence unavailable or fallback-only","INCOMPLETE":"known evidence exists but required closure is missing","BLOCKED":"policy prevents the next mutation stage"},
            "placement":{"status":placement_status,"components":placement},
            "routing":{"status":routing_status,"nets":routing,"unresolved_nets":unresolved},
            "design_status":"PASS" if placement_status=="VERIFIED" and routing_status=="VERIFIED" else "BLOCKED",
            "next_stage":"ROUTE_AND_VERIFY" if placement_status=="VERIFIED" and routing_status=="VERIFIED" else "PLACEMENT_OR_TOPOLOGY_REVIEW"}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)); print(json.dumps({"placement_status":placement_status,"routing_status":routing_status,"unresolved_topologies":sum(x["status"]=="TOPOLOGY_UNRESOLVED" for x in routing),"parser_unresolved":len(unresolved)}))
    return 0 if result["design_status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
