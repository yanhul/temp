#!/usr/bin/env python3
"""Conservative PCB routing repair planner.

Reads an existing PcbDoc and emits exact disconnected copper components and
candidate bridge segments. It NEVER mutates the source board. A candidate is
only a topology proposal; clearance/DRC/SI/return-path must be re-verified.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from collections import defaultdict

from altium_monkey import AltiumPcbDoc

def f(o,*ks):
    if isinstance(o,dict):
        for k in ks:
            if o.get(k) is not None: return o[k]
    for k in ks:
        try:
            v=getattr(o,k)
            if v is not None: return v
        except Exception: pass
    return None

def num(v):
    try: return float(v)
    except Exception: return None

def xy(o):
    for a,b in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x,y=f(o,a),f(o,b)
        if x is not None and y is not None:
            x,y=num(x),num(y)
            if x is not None and y is not None:return (x,y)
    p=f(o,"position","location","center","start")
    if p is not None:
        if isinstance(p,(list,tuple)) and len(p)>=2:
            x,y=num(p[0]),num(p[1])
            if x is not None and y is not None:return (x,y)
        x,y=f(p,"x","X"),f(p,"y","Y")
        if x is not None and y is not None:return (num(x),num(y))
    return None

def ep(o):
    vals=[f(o,k) for k in ("x1","y1","x2","y2")]
    if all(v is not None for v in vals):
        q=[num(v) for v in vals]
        if all(v is not None for v in q): return (q[0],q[1]),(q[2],q[3])
    a,b=f(o,"start"),f(o,"end")
    if a is not None and b is not None:
        a,b=xy(a),xy(b)
        if a and b:return a,b
    return None

def d(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pcb",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--nets",nargs="*",default=[])
    args=ap.parse_args()
    pcb=AltiumPcbDoc.from_file(args.pcb)
    wanted=set(args.nets)
    nets=list(getattr(pcb,"nets",[]) or [])
    result={"schema":"altium-routing-repair-plan.v1","source":str(args.pcb),
            "mode":"PLAN_ONLY_NO_MUTATION","nets":[]}
    for idx,n in enumerate(nets):
        name=f(n,"name","net_name","netname","uid")
        if name is None or (wanted and str(name) not in wanted): continue
        name=str(name)
        try: data=pcb.get_net_primitives(idx)
        except Exception: continue
        if not isinstance(data,dict): continue
        pads=list(data.get("pads",[]) or [])
        vias=list(data.get("vias",[]) or [])
        tracks=list(data.get("tracks",[]) or [])
        arcs=list(data.get("arcs",[]) or [])
        nodes=[]
        meta=[]
        for p in pads:
            q=xy(p)
            if q: nodes.append(q); meta.append({"kind":"pad","designator":f(p,"designator","component","refdes"),"pin":f(p,"designator","pin","pad_name"),"xy":q,"layer":f(p,"layer","layer_name")})
        for v in vias:
            q=xy(v)
            if q: nodes.append(q); meta.append({"kind":"via","xy":q})
        for typ,items in (("track",tracks),("arc",arcs)):
            for obj in items:
                z=ep(obj)
                if z:
                    nodes.extend(z); meta.extend([{"kind":typ,"xy":z[0],"layer":f(obj,"layer","layer_name")},{"kind":typ,"xy":z[1],"layer":f(obj,"layer","layer_name")}])
        if len(nodes)<2: continue
        parent=list(range(len(nodes)))
        def find(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]]; i=parent[i]
            return i
        def union(a,b):
            a,b=find(a),find(b)
            if a!=b: parent[b]=a
        snap=defaultdict(list)
        for i,p in enumerate(nodes): snap[(round(p[0]),round(p[1]))].append(i)
        for ids in snap.values():
            for j in ids[1:]: union(ids[0],j)
        for obj in tracks+arcs:
            z=ep(obj)
            if not z: continue
            ia=next((i for i,p in enumerate(nodes) if p==z[0]),None)
            ib=next((i for i,p in enumerate(nodes) if p==z[1]),None)
            if ia is not None and ib is not None: union(ia,ib)
        comps=defaultdict(list)
        for i in range(len(nodes)): comps[find(i)].append(i)
        if len(comps)<=1: continue
        groups=[]
        for ids in comps.values():
            groups.append([meta[i] for i in ids])
        # Build a conservative spanning set: one shortest pad/via bridge
        # from the already-connected component set to the nearest unconnected
        # component. This produces component_count-1 candidates rather than
        # the old single bridge, so multi-component nets can actually converge.
        bridges=[]
        if len(groups)>1:
            connected={0}
            while len(connected)<len(groups):
                best=None
                best_b=None
                for a in sorted(connected):
                    for b in range(len(groups)):
                        if b in connected: continue
                        for u in groups[a]:
                            if u["kind"] not in ("pad","via"): continue
                            for v in groups[b]:
                                if v["kind"] not in ("pad","via"): continue
                                dist=d(u["xy"],v["xy"])
                                if best is None or dist<best["distance_mils"]:
                                    best={"from":u,"to":v,"distance_mils":dist}
                                    best_b=b
                if best is None: break
                bridges.append(best)
                connected.add(best_b)
        result["nets"].append({"name":name,"component_count":len(groups),
            "components":groups,"nearest_component_bridges":bridges,
            "tracks":len(tracks),"vias":len(vias)})
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"nets_with_disconnected_graph":len(result["nets"]),"out":str(args.out)}))
if __name__=="__main__": main()
