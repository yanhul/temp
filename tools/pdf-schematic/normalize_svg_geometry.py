#!/usr/bin/env python3
"""Normalize SVG geometry for schematic reconstruction.

This module deliberately does NOT infer electrical connectivity. It resolves
SVG transforms and <use> references, expands path commands into geometric
segments, and emits stable evidence records. Unsupported/malformed geometry is
retained as an explicit issue rather than silently discarded.
"""
from __future__ import annotations
import math, re
import xml.etree.ElementTree as ET
from pathlib import Path

_NUM = re.compile(r"[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?")
_CMD = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?")
_ID = "{http://www.w3.org/XML/1998/namespace}id"

def local(tag):
    return tag.rsplit("}", 1)[-1]

def mmul(a, b):
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5])

def parse_transform(value):
    """Parse an SVG transform list into one affine matrix."""
    result = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    token = r"[-+]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)(?:[eE][-+]?[0-9]+)?"
    for item in re.finditer(r"([A-Za-z]+) *[(]([^)]*)[)]", value or ""):
        name = item.group(1).lower()
        values = [float(v) for v in re.findall(token, item.group(2))]
        if name == "matrix" and len(values) == 6:
            transform = tuple(values)
        elif name == "translate" and len(values) in (1, 2):
            transform = (1.0, 0.0, 0.0, 1.0, values[0], values[1] if len(values) == 2 else 0.0)
        elif name == "scale" and len(values) in (1, 2):
            transform = (values[0], 0.0, 0.0, values[1] if len(values) == 2 else values[0], 0.0, 0.0)
        elif name == "rotate" and len(values) in (1, 3):
            angle = math.radians(values[0])
            cosine, sine = math.cos(angle), math.sin(angle)
            rotation = (cosine, sine, -sine, cosine, 0.0, 0.0)
            if len(values) == 3:
                cx, cy = values[1], values[2]
                transform = mmul((1, 0, 0, 1, cx, cy), mmul(rotation, (1, 0, 0, 1, -cx, -cy)))
            else:
                transform = rotation
        elif name == "skewx" and len(values) == 1:
            transform = (1.0, 0.0, math.tan(math.radians(values[0])), 1.0, 0.0, 0.0)
        elif name == "skewy" and len(values) == 1:
            transform = (1.0, math.tan(math.radians(values[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = mmul(result, transform)
    return result

def point(m,x,y):
    return [m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]]

def path_segments(d):
    tok=_CMD.findall(d or "")
    i=0; cmd=None; x=y=sx=sy=0.; out=[]; prev_c=None; prev_q=None
    arity={"M":2,"L":2,"H":1,"V":1,"C":6,"S":4,"Q":4,"T":2,"A":7,"Z":0}
    while i<len(tok):
        if tok[i].isalpha(): cmd=tok[i]; i+=1
        if cmd is None: raise ValueError("path data starts without command")
        up=cmd.upper(); rel=cmd.islower(); n=arity[up]
        if up=="Z":
            out.append(("L",(x,y),(sx,sy))); x,y=sx,sy; prev_c=prev_q=None; cmd=None; continue
        if i+n>len(tok) or any(t.isalpha() for t in tok[i:i+n]): raise ValueError("incomplete path command "+cmd)
        v=list(map(float,tok[i:i+n])); i+=n
        def xy(a,b): return (x+a,y+b) if rel else (a,b)
        if up=="M":
            x,y=xy(*v); sx,sy=x,y; cmd="l" if rel else "L"; prev_c=prev_q=None; continue
        if up=="L": p=xy(*v); out.append(("L",(x,y),p)); x,y=p
        elif up=="H": nx=x+v[0] if rel else v[0]; out.append(("L",(x,y),(nx,y))); x=nx
        elif up=="V": ny=y+v[0] if rel else v[0]; out.append(("L",(x,y),(x,ny))); y=ny
        elif up in ("C","S"):
            if up=="C": c1=xy(v[0],v[1]); c2=xy(v[2],v[3]); p=xy(v[4],v[5])
            else: c1=(2*x-prev_c[0],2*y-prev_c[1]) if prev_c else (x,y); c2=xy(v[0],v[1]); p=xy(v[2],v[3])
            out.append(("C",(x,y),c1,c2,p)); x,y=p; prev_c=c2; prev_q=None; continue
        elif up in ("Q","T"):
            if up=="Q": c=xy(v[0],v[1]); p=xy(v[2],v[3])
            else: c=(2*x-prev_q[0],2*y-prev_q[1]) if prev_q else (x,y); p=xy(v[0],v[1])
            out.append(("Q",(x,y),c,p)); x,y=p; prev_q=c; prev_c=None; continue
        elif up=="A":
            p=xy(v[5],v[6]); out.append(("A",(x,y),tuple(v[:5]),p)); x,y=p
        prev_c=prev_q=None
    return out

def _index(root):
    return {e.get("id") or e.get(_ID):e for e in root.iter() if e.get("id") or e.get(_ID)}

def normalize_svg(path):
    root=ET.parse(path).getroot(); ids=_index(root); records=[]; issues=[]
    supported={"path","line","polyline","polygon","rect","circle","ellipse","text","tspan"}
    containers={"svg","g","defs","symbol","clipPath","mask","pattern","marker","title","desc","metadata","style"}
    def visit(el,parent,stack,depth=0,from_use=False):
        if depth>32: issues.append({"kind":"use_depth_limit"}); return
        tag=local(el.tag)
        if tag in {"defs","symbol","clipPath","mask","pattern","marker"} and not from_use:
            return
        m=mmul(parent,parse_transform(el.get("transform","")))
        if tag=="use":
            href=el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
            target=ids.get(href.lstrip("#"))
            if target is None: issues.append({"kind":"unresolved_use","href":href}); return
            if id(target) in stack: issues.append({"kind":"cyclic_use","href":href}); return
            tx=float(el.get("x","0")); ty=float(el.get("y","0"))
            visit(target,mmul(m,(1,0,0,1,tx,ty)),stack|{id(target)},depth+1,True); return
        if tag in supported:
            base={"tag":tag,"transform":list(m),"source_id":el.get("id")}
            try:
                if tag=="path":
                    segs=path_segments(el.get("d",""))
                    base["segments"]=[{"type":s[0],"points":[point(m,*p) if isinstance(p,tuple) and len(p)==2 else p for p in s[1:]]} for s in segs]
                elif tag=="line": base["segments"]=[{"type":"L","points":[point(m,float(el.get("x1",0)),float(el.get("y1",0))),point(m,float(el.get("x2",0)),float(el.get("y2",0)))]}]
                elif tag in ("polyline","polygon"):
                    vals=[float(x) for x in _NUM.findall(el.get("points",""))]
                    pts=[point(m,vals[i],vals[i+1]) for i in range(0,len(vals)-1,2)]
                    base["points"]=pts
                    if tag=="polygon" and len(pts)>2: base["points"].append(pts[0])
                elif tag in ("rect","circle","ellipse"):
                    a={k:float(el.get(k,"0")) for k in ("x","y","width","height","cx","cy","r","rx","ry")}
                    if tag=="rect":
                        x,y,w,h=a["x"],a["y"],a["width"],a["height"]
                        base["geometry"]={"kind":"transformed_polygon","points":[point(m,x,y),point(m,x+w,y),point(m,x+w,y+h),point(m,x,y+h)]}
                    else:
                        cx,cy=a["cx"],a["cy"]; rx=a["r"] if tag=="circle" else a["rx"]; ry=a["r"] if tag=="circle" else a["ry"]
                        base["geometry"]={"kind":"transformed_ellipse","center":point(m,cx,cy),"axis_x":[m[0]*rx,m[1]*rx],"axis_y":[m[2]*ry,m[3]*ry]}
                elif tag in ("text","tspan"):
                    x=float(el.get("x","0")); y=float(el.get("y","0"))
                    base["text"]={"value":"".join(el.itertext()),"anchor":point(m,x,y)}
                records.append(base)
            except Exception as exc: issues.append({"kind":"geometry_parse_error","tag":tag,"id":el.get("id"),"error":str(exc)})
        elif tag not in containers and tag not in {"use"}:
            issues.append({"kind":"unsupported_svg_element","tag":tag,"id":el.get("id")})
        for child in list(el): visit(child,m,stack,depth,from_use)
    visit(root,(1,0,0,1,0,0),set())
    return {"schema":"pdf-schematic-normalized-geometry/v1","source":str(path),
            "element_count":len(records),"issue_count":len(issues),"elements":records,"issues":issues,
            "policy":{"connectivity_inferred":False,"unsupported_geometry_is_not_silently_dropped":True,"supported_primitives":sorted(supported),"viewbox_to_viewport_mapping_applied":False}}

if __name__=="__main__":
    import argparse,json
    ap=argparse.ArgumentParser(); ap.add_argument("svg"); ap.add_argument("--out",required=True)
    a=ap.parse_args(); data=normalize_svg(a.svg)
    Path(a.out).write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:data[k] for k in ("schema","element_count","issue_count","policy")}))
    if data["issue_count"]: raise SystemExit(2)
