#!/usr/bin/env python3
"""Evidence-first placement and routing topology planner.

This module plans; it never mutates a PCB. It reports what can be proven from
the parsed PCB and explicitly leaves topology decisions unresolved when the
available evidence is insufficient.
"""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from pathlib import Path
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
            if x is not None and y is not None:return (x,y)
    p=f(o,"position","location","center")
    if p is not None:
        if isinstance(p,(tuple,list)) and len(p)>=2:
            x,y=num(p[0]),num(p[1])
            if x is not None and y is not None:return (x,y)
        x,y=f(p,"x","X"),f(p,"y","Y")
        if x is not None and y is not None:return (num(x),num(y))
    return None

def dist(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])

def endpoint(o):
    vals=[f(o,k) for k in ("x1","y1","x2","y2")]
    if all(v is not None for v in vals):
        q=[num(v) for v in vals]
        if all(v is not None for v in q):return (q[0],q[1]),(q[2],q[3])
    return None

def components_for_net(data):
    pads=[xy(x) for x in data.get("pads",[]) or [] if xy(x) is not None]
    vias=[xy(x) for x in data.get("vias",[]) or [] if xy(x) is not None]
    routes=[]
    for obj in list(data.get("tracks",[]) or [])+list(data.get("arcs",[]) or []):
        z=endpoint(obj)
        if z:routes.append(z)
    nodes=pads+vias+[p for z in routes for p in z]
    if len(nodes)<2:return len(nodes),0
    parent=list(range(len(nodes)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    buckets=defaultdict(list)
    for i,p in enumerate(nodes):buckets[(round(p[0]),round(p[1]))].append(i)
    for ids in buckets.values():
        for j in ids[1:]:union(ids[0],j)
    for a,b in routes:
        ia=next((i for i,p in enumerate(nodes) if p==a),None)
        ib=next((i for i,p in enumerate(nodes) if p==b),None)
        if ia is not None and ib is not None:union(ia,ib)
    return len(nodes),len({find(i) for i in range(len(nodes))})

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pcb",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    pcb=AltiumPcbDoc.from_file(args.pcb)
    comps=list(getattr(pcb,"components",[]) or [])
    nets=list(getattr(pcb,"nets",[]) or [])
    placement=[]
    for i,c in enumerate(comps):
        ref=f(c,"designator","refdes","reference","name")
        p=xy(c)
        placement.append({"component_index":i,"reference":str(ref) if ref is not None else None,
                          "position":p,"placement_status":"VERIFIED" if p else "UNKNOWN"})
    routing=[]
    unresolved=[]
    for i,n in enumerate(nets):
        name=f(n,"name","net_name","netname","uid")
        if name is None:continue
        try:data=pcb.get_net_primitives(i)
        except Exception:
            unresolved.append(str(name));continue
        if not isinstance(data,dict): unresolved.append(str(name));continue
        node_count,component_count=components_for_net(data)
        if component_count>1:
            pads=data.get("pads",[]) or []
            terminals=[{"xy":xy(p),"designator":f(p,"designator","pad_designator","number")}
                       for p in pads if xy(p) is not None]
            routing.append({
                "net":str(name),"status":"TOPOLOGY_UNRESOLVED",
                "graph_components":component_count,"node_count":node_count,
                "endpoints":terminals,
                "placement_dependency":"REVIEW",
                "candidate_topology":"NOT_SELECTED",
                "reason":"Disconnected copper is proven, but no authoritative placement/topology decision permits automatic bridging."
            })
        else:
            routing.append({"net":str(name),"status":"CONNECTED",
                            "graph_components":component_count,"node_count":node_count})
    placement_unknown=[x for x in placement if x["placement_status"]!="VERIFIED"]
    placement_status="VERIFIED" if not placement_unknown else "UNKNOWN"
    routing_status="VERIFIED" if not routing and not unresolved else ("BLOCKED" if unresolved else "INCOMPLETE")
    result={
        "schema":"altium-placement-routing-plan.v1",
        "mode":"PLAN_ONLY_NO_MUTATION",
        "placement":{"status":placement_status,"components":placement},
        "routing":{"status":routing_status,"nets":routing,"unresolved_nets":unresolved},
        "design_status":"PASS" if placement_status=="VERIFIED" and routing_status=="VERIFIED" else "BLOCKED",
        "next_stage":"ROUTE_AND_VERIFY" if routing_status=="VERIFIED" else "PLACEMENT_OR_TOPOLOGY_REVIEW"
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"placement_status":placement_status,"routing_status":routing_status,
                      "unresolved_topologies":len(routing),"parser_unresolved":len(unresolved)}))
    return 0 if result["design_status"]=="PASS" else 1

if __name__=="__main__":raise SystemExit(main())
