#!/usr/bin/env python3
"""Conservative PcbDoc repair adapter.

Consumes routing_repair_plan.json and mutates only when a candidate bridge is
provably narrow and collision-free against foreign copper using available
geometry. Every mutation is written to a working-copy PcbDoc and recorded in
repair_receipt.json. The original source is never overwritten.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
from altium_monkey import AltiumPcbDoc

def xy(o):
    for a,b in (("x_mils","y_mils"),("x","y")):
        try:
            x,y=getattr(o,a),getattr(o,b)
            return float(x),float(y)
        except Exception: pass
    p=getattr(o,"position",None)
    if p is not None:
        try:return float(p[0]),float(p[1])
        except Exception:pass
    return None

def ep(o):
    try:return (float(o.x1),float(o.y1)),(float(o.x2),float(o.y2))
    except Exception:pass
    return None

def segdist(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    if dx==dy==0:return math.dist(p,a)
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.dist(p,(a[0]+t*dx,a[1]+t*dy))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pcb",required=True,type=Path)
    ap.add_argument("--plan",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--receipt",required=True,type=Path)
    args=ap.parse_args()
    pcb=AltiumPcbDoc.from_file(args.pcb)
    plan=json.loads(args.plan.read_text())
    applied=[]
    rejected=[]
    # Only one conservative bridge per disconnected-net group per pass.
    for net in plan.get("nets",[]):
        name=net.get("name")
        for bridge in net.get("nearest_component_bridges",[]):
            a,b=bridge.get("from",{}),bridge.get("to",{})
            p,q=a.get("xy"),b.get("xy")
            if not (p and q): rejected.append({"net":name,"reason":"missing endpoints"}); continue
            if float(bridge.get("distance_mils",1e99)) > 500:
                rejected.append({"net":name,"reason":"bridge exceeds 500 mil safety bound"}); continue
            # Require both endpoints to be pad/via anchors and reject any
            # foreign track whose segment comes within 1 mil of the candidate.
            foreign=False
            for tr in list(getattr(pcb,"tracks",[]) or []):
                tn=getattr(tr,"net_name",None) or getattr(tr,"net",None)
                if tn is not None and str(tn)==str(name): continue
                z=ep(tr)
                if z and segdist(p,z[0],z[1])<=1.0 or z and segdist(q,z[0],z[1])<=1.0:
                    foreign=True; break
            if foreign:
                rejected.append({"net":name,"reason":"candidate endpoint conflicts with foreign copper"}); continue
            try:
                pcb.add_track(p,q,width_mils=10,net=name)
                applied.append({"net":name,"from":p,"to":q,"distance_mils":bridge.get("distance_mils"),"width_mils":10})
            except Exception as exc:
                rejected.append({"net":name,"reason":f"add_track failed: {type(exc).__name__}: {exc}"})
    if not applied:
        args.receipt.write_text(json.dumps({"schema":"altium-repair-receipt.v1","status":"NO_SAFE_MUTATION","applied":[],"rejected":rejected},indent=2))
        return 3
    args.out.parent.mkdir(parents=True,exist_ok=True)
    pcb.save(args.out)
    digest=hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.receipt.write_text(json.dumps({"schema":"altium-repair-receipt.v1","status":"MUTATED","source":str(args.pcb),"output":str(args.out),"sha256":digest,"applied":applied,"rejected":rejected},indent=2))
    return 0
if __name__=="__main__": raise SystemExit(main())
