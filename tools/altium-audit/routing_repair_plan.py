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
    result={"schema":"altium-routing-repair-plan.v2","source":str(args.pcb),
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

        nodes=[]; meta=[]; tolerances=[]
        for p in pads:
            q=xy(p)
            if q:
                w=num(f(p,"width_mils","width")) or 0.0
                h=num(f(p,"height_mils","height")) or 0.0
                nodes.append(q)
                meta.append({"kind":"pad","designator":f(p,"designator","component","refdes"),
                             "pin":f(p,"designator","pin","pad_name"),"xy":q,
                             "layer":f(p,"layer","layer_name")})
                tolerances.append(max(1.0,math.hypot(w,h)/2.0))
        for v in vias:
            q=xy(v)
            if q:
                dia=num(f(v,"diameter_mils","diameter")) or 0.0
                nodes.append(q)
                meta.append({"kind":"via","xy":q,"layer_start":f(v,"layer_start"),
                             "layer_end":f(v,"layer_end")})
                tolerances.append(max(1.0,dia/2.0))
        route_edges=[]
        for typ,items in (("track",tracks),("arc",arcs)):
            for obj in items:
                z=ep(obj)
                if z:
                    ia=len(nodes)
                    layer=f(obj,"layer","layer_name")
                    nodes.extend(z)
                    meta.extend([
                        {"kind":typ,"xy":z[0],"layer":layer},
                        {"kind":typ,"xy":z[1],"layer":layer}
                    ])
                    tolerances.extend([1.0,1.0])
                    # A track/arc is itself continuous copper: connect its
                    # endpoints directly, independent of pads/vias touching it.
                    route_edges.append((ia,ia+1,z[0],z[1]))

        if len(nodes)<2: continue

        parent=list(range(len(nodes)))
        def find(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]]
                i=parent[i]
            return i
        def union(a,b):
            a,b=find(a),find(b)
            if a!=b: parent[b]=a

        # Join coincident copper only when layers can physically connect.
        # Through vias and multilayer pads are the explicit cross-layer bridges.
        def layer_key(value):
            return str(value).strip().upper().replace("_","-") if value is not None else ""
        def multilayer(item):
            return layer_key(item.get("layer")) in {"74","MULTI-LAYER","MULTILAYER","MULTI LAYER"}
        snap=defaultdict(list)
        for i,p in enumerate(nodes):
            snap[(round(p[0]),round(p[1]))].append(i)
        for ids in snap.values():
            for pos,i in enumerate(ids):
                for j in ids[pos+1:]:
                    mi,mj=meta[i],meta[j]
                    if mi["kind"]=="via" or mj["kind"]=="via" or multilayer(mi) or multilayer(mj):
                        union(i,j)
                    elif layer_key(mi.get("layer"))==layer_key(mj.get("layer")):
                        union(i,j)
        # Do not rely on a pad/via intersection to connect the endpoints of
        # the same copper primitive; that omission caused false islands and
        # repeated identical repair attempts.
        for ia,ib,_,_ in route_edges:
            union(ia,ib)

        def point_segment_distance(p,a,b):
            dx,dy=b[0]-a[0],b[1]-a[1]
            if dx==dy==0:return d(p,a)
            t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
            q=(a[0]+t*dx,a[1]+t*dy)
            return d(p,q)

        # Join pads/vias to route interiors using their actual copper envelope.
        # This is the critical difference from v1, which produced false
        # "disconnected" reports for essentially every routed net.
        for i,(p,kind) in enumerate(zip(nodes,meta)):
            if kind["kind"] not in ("pad","via"): continue
            tol=tolerances[i]
            for ia,ib,a,b in route_edges:
                # A surface-mount pad only touches copper on its own layer.
                # A via is the explicit layer transition; multilayer pads may
                # also contact more than one copper layer.
                if kind["kind"]=="pad" and not multilayer(kind):
                    pad_layer=layer_key(kind.get("layer"))
                    route_layer=layer_key(meta[ia].get("layer"))
                    if pad_layer != route_layer:
                        continue
                if point_segment_distance(p,a,b)<=tol:
                    union(i,ia); union(i,ib)

        comps=defaultdict(list)
        for i in range(len(nodes)): comps[find(i)].append(i)
        if len(comps)<=1: continue

        groups=[[meta[i] for i in ids] for ids in comps.values()]
        bridges=[]
        connected={0}
        while len(connected)<len(groups):
            best=None; best_b=None
            for a in sorted(connected):
                for b in range(len(groups)):
                    if b in connected: continue
                    for u in groups[a]:
                        if u["kind"] not in ("pad","via"): continue
                        for v in groups[b]:
                            if v["kind"] not in ("pad","via"): continue
                            dist=d(u["xy"],v["xy"])
                            if best is None or dist<best["distance_mils"]:
                                best={"from":u,"to":v,"distance_mils":dist}; best_b=b
            if best is None: break
            bridges.append(best); connected.add(best_b)

        result["nets"].append({
            "name":name,"component_count":len(groups),"components":groups,
            "nearest_component_bridges":bridges,"tracks":len(tracks),"vias":len(vias)}
        )

    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"nets_with_disconnected_graph":len(result["nets"]),"out":str(args.out)}))

if __name__=="__main__": main()
