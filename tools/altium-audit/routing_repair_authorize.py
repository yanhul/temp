#!/usr/bin/env python3
"""Independent authorization gate for conservative PCB routing repair."""
from __future__ import annotations
import argparse, hashlib, json, math, re
from pathlib import Path
from altium_monkey import AltiumPcbDoc

def field(o,*keys):
    if isinstance(o,dict):
        for k in keys:
            if o.get(k) is not None:return o[k]
    for k in keys:
        try:
            v=getattr(o,k)
            if v is not None:return v
        except Exception:pass
    return None

def xy(o):
    for a,b in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x,y=field(o,a),field(o,b)
        try:
            if x is not None and y is not None:return float(x),float(y)
        except Exception:pass
    p=field(o,"position","location","center")
    if isinstance(p,(list,tuple)) and len(p)>=2:
        try:return float(p[0]),float(p[1])
        except Exception:pass
    if p is not None:
        x,y=field(p,"x","X"),field(p,"y","Y")
        try:
            if x is not None and y is not None:return float(x),float(y)
        except Exception:pass
    return None

def ep(o):
    vals=[field(o,k) for k in ("x1","y1","x2","y2")]
    try:
        if all(v is not None for v in vals):return (float(vals[0]),float(vals[1])),(float(vals[2]),float(vals[3]))
    except Exception:pass
    a,b=field(o,"start"),field(o,"end")
    if a is not None and b is not None:
        a,b=xy(a),xy(b)
        if a and b:return a,b
    return None

def pd(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    if dx==dy==0:return math.dist(p,a)
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.dist(p,(a[0]+t*dx,a[1]+t*dy))

def sd(a,b,c,d):
    def o(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    def on(p,q,r): return abs(o(p,q,r))<1e-9 and min(p[0],r[0])<=q[0]<=max(p[0],r[0]) and min(p[1],r[1])<=q[1]<=max(p[1],r[1])
    o1,o2,o3,o4=o(a,b,c),o(a,b,d),o(c,d,a),o(c,d,b)
    if ((o1>0>o2) or (o2>0>o1)) and ((o3>0>o4) or (o4>0>o3)): return 0.0
    if on(a,c,b) or on(a,d,b) or on(c,a,d) or on(c,b,d): return 0.0
    return min(pd(a,c,d),pd(b,c,d),pd(c,a,b),pd(d,a,b))

def mil(v):
    if v is None:return None
    m=re.search(r"[-+]?\d+(?:\.\d+)?",str(v))
    return float(m.group(0)) if m else None

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for c in iter(lambda:f.read(1048576),b""):h.update(c)
    return h.hexdigest()

def graph(pcb,name):
    nets=list(getattr(pcb,"nets",[]) or [])
    idx=next((i for i,n in enumerate(nets) if str(field(n,"name","net_name","netname","uid"))==name),None)
    if idx is None:return None
    data=pcb.get_net_primitives(idx)
    if not isinstance(data,dict):return None
    nodes=[]; edges=[]
    for p in data.get("pads",[]) or []:
        q=xy(p)
        if q:nodes.append(("pad",q,p))
    for v in data.get("vias",[]) or []:
        q=xy(v)
        if q:nodes.append(("via",q,v))
    for o in list(data.get("tracks",[]) or [])+list(data.get("arcs",[]) or []):
        z=ep(o)
        if z:
            nodes.extend([("route",z[0],o),("route",z[1],o)])
            edges.append(z)
    if len(nodes)<2:return None
    parent=list(range(len(nodes)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[b]=a
    snap={}
    for i,(_,p,_) in enumerate(nodes):snap.setdefault((round(p[0]),round(p[1])),[]).append(i)
    for ids in snap.values():
        for j in ids[1:]:union(ids[0],j)
    for a,b in edges:
        ia=next((i for i,x in enumerate(nodes) if x[0]=="route" and x[1]==a),None)
        ib=next((i for i,x in enumerate(nodes) if x[0]=="route" and x[1]==b),None)
        if ia is not None and ib is not None:union(ia,ib)
    comps={}
    for i in range(len(nodes)):comps.setdefault(find(i),[]).append(i)
    return nodes,comps

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pcb",required=True,type=Path);ap.add_argument("--plan",required=True,type=Path)
    ap.add_argument("--findings",required=True,type=Path);ap.add_argument("--probe",required=True,type=Path)
    args=ap.parse_args()
    plan=json.loads(args.plan.read_text()); raw=json.loads(args.findings.read_text())
    findings=raw if isinstance(raw,list) else raw.get("findings",[])
    pcb=AltiumPcbDoc.from_file(args.pcb)
    topo={str(f.get("object")):f for f in findings if f.get("id","").startswith("G7-TOPOLOGY-")}
    probe=json.loads(args.probe.read_text())
    clear=[]
    for r in probe.get("rule_samples",[]) or []:
        a=r.get("attrs",{}) or {}
        if str(a.get("rule_kind","")).lower()!="clearance": continue
        scope=str(a.get("net_scope",a.get("netscope","DifferentNets"))).lower()
        if "differentnets" not in scope and scope not in ("anynet","any"): continue
        rawr=r.get("raw_rule",{}) or {}
        for k in ("clearance","minimum_clearance","gap","generic_clearance","value"):
            v=mil(a.get(k))
            if v is not None: clear.append(v); break
        else:
            for k in ("CLEARANCE","MINIMUMCLEARANCE","MINCLEARANCE","GAP","GENERICCLEARANCE","VALUE"):
                v=mil(rawr.get(k))
                if v is not None: clear.append(v); break
    def block(reason,rejected=None):
        plan["mutation_authorized"]=False
        plan["authorization"]={"status":"BLOCKED","reason":reason,"rejected":rejected or []}
        args.plan.write_text(json.dumps(plan,indent=2,sort_keys=True))
        return 3
    if not topo:return block("no authoritative G7 topology finding")
    if not clear:return block("authoritative clearance rule is not exposed; no clearance value is guessed")
    clearance=max(clear);authorized=[];rejected=[]
    for net in plan.get("nets",[]) or []:
        name=str(net.get("name")); finding=topo.get(name)
        if not finding or finding.get("status")!="FAIL" or finding.get("severity") not in ("HIGH","BLOCKER"):
            rejected.append({"net":name,"reason":"no matching verified topology failure"});continue
        g=graph(pcb,name)
        if not g:rejected.append({"net":name,"reason":"authoritative net graph unavailable"});continue
        nodes,comps=g; comp={}
        for cid,ids in comps.items():
            for i in ids:comp[tuple(nodes[i][1])]=cid
        for bridge in net.get("nearest_component_bridges",[]) or []:
            a,b=bridge.get("from",{}),bridge.get("to",{})
            p,q=tuple(a.get("xy",[])),tuple(b.get("xy",[]))
            if len(p)!=2 or len(q)!=2:rejected.append({"net":name,"reason":"missing endpoints"});continue
            if comp.get(p) is None or comp.get(q) is None or comp[p]==comp[q]:
                rejected.append({"net":name,"reason":"endpoints not proven in distinct components"});continue
            if a.get("kind") not in ("pad","via") or b.get("kind") not in ("pad","via"):
                rejected.append({"net":name,"reason":"endpoints are not pad/via anchors"});continue
            bad=False
            for tr in list(getattr(pcb,"tracks",[]) or []):
                tn=field(tr,"net_name","netname","net")
                if tn is not None and str(tn)==name:continue
                z=ep(tr)
                if z and sd(p,q,*z)<clearance:bad=True;break
            if bad:rejected.append({"net":name,"reason":f"foreign-track clearance below {clearance:g} mil"});continue
            authorized.append({**bridge,"net":name,"clearance_mils":clearance,
                               "evidence":{"finding_id":finding["id"],"source_sha256":sha(args.pcb)}})
    if not authorized:return block("no candidate passed independent evidence and geometry validation",rejected)
    bynet={}
    for x in authorized:bynet.setdefault(x["net"],[]).append(x)
    plan["nets"]=[{"name":n,"nearest_component_bridges":v} for n,v in bynet.items()]
    plan["mutation_authorized"]=True
    plan["authorization"]={"status":"AUTHORIZED","method":"routing_evidence_authorizer.v1",
                           "pcb_sha256":sha(args.pcb),"clearance_mils":clearance,"rejected":rejected}
    args.plan.write_text(json.dumps(plan,indent=2,sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(main())
