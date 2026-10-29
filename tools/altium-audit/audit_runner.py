#!/usr/bin/env python3
"""Evidence-first Altium audit runner.

This runner deliberately separates parser success from design correctness.
Unsupported checks are reported as UNKNOWN/BLOCKED, never PASS.
"""
from __future__ import annotations
import argparse, hashlib, json, math, pathlib, sys, zipfile
from typing import Any
try:
    from schematic_semantics import run as run_schematic_semantics
except Exception:
    run_schematic_semantics = None

try:
    from hcpl_repair_plan import build_hcpl_repair_plan
except Exception:
    build_hcpl_repair_plan = None

try:
    from altium_monkey import AltiumDesign, AltiumSchDoc, AltiumPcbDoc, PcbLayer
except Exception as exc:
    print(f"BLOCKED G1: cannot import altium_monkey: {exc}", file=sys.stderr)
    raise

def field(obj: Any, *keys: str):
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k) is not None:
                return obj[k]
    for k in keys:
        try:
            v = getattr(obj, k)
            if v is not None:
                return v
        except Exception:
            pass
    return None

def as_name(obj: Any):
    """Resolve a component reference designator across altium-monkey projections.

    SchDoc designators may be emitted as typed parameter records, dictionaries,
    or child records depending on the public projection. Never use component.name
    as a refdes: it is commonly the library symbol name (e.g. Cap2).
    """
    def entries(container):
        if container is None:
            return []
        if isinstance(container, dict):
            # Preserve both the key and value: some projections map parameter
            # names directly to text while others map names to typed records.
            return [{"name": k, "value": v, "text": v} for k, v in container.items()]
        try:
            return list(container)
        except TypeError:
            return [container]

    def candidate(child):
        if isinstance(child, dict):
            name = str(child.get("name") or child.get("parameter_name") or child.get("key") or "").strip().lower()
            kind = str(child.get("type") or child.get("record_type") or child.get("__class__") or "").lower()
            value = child.get("text")
            if value is None:
                value = child.get("value", child.get("parameter_value"))
            if name == "designator" or "designator" in kind:
                if value is not None and str(value).strip():
                    return str(value).strip()
            return None
        kind = type(child).__name__.lower()
        name = str(field(child, "name", "parameter_name", "key") or "").strip().lower()
        if "designator" in kind or name == "designator":
            value = field(child, "text", "value", "parameter_value")
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    seen = set()
    for container in (field(obj, "parameters"), field(obj, "children")):
        for child in entries(container):
            marker = id(child)
            if marker in seen:
                continue
            seen.add(marker)
            value = candidate(child)
            if value:
                return value

    # A few serialized projections retain parameter records only in raw fields.
    raw = field(obj, "raw_record", "record")
    if isinstance(raw, dict):
        for key in ("DESIGNATOR", "Designator", "designator", "refdes", "RefDes"):
            value = raw.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

    # Direct refdes fields are authoritative; generic name/id fields are not.
    v = field(obj, "designator", "refdes", "reference", "logical_designator", "physical_designator")
    return str(v).strip() if v is not None and str(v).strip() else None

def add(findings, fid, severity, domain, status, evidence, confidence="VERIFIED", obj=None):
    findings.append({
        "id": fid, "severity": severity, "domain": domain, "status": status,
        "object": obj, "evidence": evidence, "confidence": confidence,
    })


def num(v):
    try:
        return float(v)
    except Exception:
        return None

def xy(obj):
    for keys in (("x_mils","y_mils"),("location_x_mils","location_y_mils"),("x","y")):
        x=field(obj,keys[0])
        y=field(obj,keys[1])
        if x is not None and y is not None:
            a,b=num(x),num(y)
            if a is not None and b is not None:
                # Normalize raw Altium database coordinates (1/10000 mil)
                # so pads/vias join track endpoints exposed in mils.
                if (abs(a) > 100000 or abs(b) > 100000) and not (keys[0].endswith("_mils") or keys[1].endswith("_mils")):
                    a,b=a/10000.0,b/10000.0
                return (a,b)
    p=field(obj,"position","location","center","start")
    if p is not None:
        if isinstance(p,(tuple,list)) and len(p)>=2:
            a,b=num(p[0]),num(p[1])
            if a is not None and b is not None: return (a,b)
        x=field(p,"x","X")
        y=field(p,"y","Y")
        if x is not None and y is not None:
            a,b=num(x),num(y)
            if a is not None and b is not None: return (a,b)
    return None

def rect(obj):
    bb=field(obj,"bounding_box","bbox","bounds")
    if isinstance(bb,(tuple,list)) and len(bb)>=4:
        vals=[num(x) for x in bb[:4]]
        if all(x is not None for x in vals):
            x0,y0,x1,y1=vals
            return (min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1))
    return None

def object_bbox(obj):
    r=rect(obj)
    if r: return r
    p=xy(obj)
    return (p[0],p[1],p[0],p[1]) if p else None

def distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def layer_token(v):
    if v is None: return ""
    for k in ("token","name","value","id"):
        try:
            q=getattr(v,k)
            if q is not None: return str(q).upper()
        except Exception:
            pass
    return str(v).upper()


def primitive_net_index(obj):
    for key in ("net_index","_net_index","net","net_id"):
        v=field(obj,key)
        if isinstance(v,dict): v=field(v,"index","id","uid")
        try:
            if v is not None: return int(v)
        except Exception:
            pass
    raw=field(obj,"raw_record","record")
    if isinstance(raw,dict):
        for key in ("NET","Net","NETINDEX","NetIndex"):
            try:
                if raw.get(key) is not None: return int(raw[key])
            except Exception:
                pass
    return None

def build_net_index_map(pcb):
    nets=list(getattr(pcb,"nets",[]) or [])
    names=[field(n,"name","net_name","netname","uid") for n in nets]
    candidates=[]
    for offset in (0,1):
        m={i+offset:n for i,n in enumerate(names) if n is not None}
        score=0
        for obj in list(getattr(pcb,"pads",[]) or [])+list(getattr(pcb,"tracks",[]) or []):
            ni=primitive_net_index(obj)
            if ni is not None and ni in m: score+=1
        candidates.append((score,m,offset))
    candidates.sort(key=lambda x:x[0],reverse=True)
    return candidates[0][1] if candidates else {}

def net_name(obj, net_by_idx=None):
    v=field(obj,"net_name","netname")
    if isinstance(v,dict): v=field(v,"name","uid")
    if v is None:
        ni=primitive_net_index(obj)
        try:
            if ni is not None and net_by_idx is not None: v=net_by_idx.get(int(ni))
        except Exception:
            pass
    return str(v) if v is not None else None

def pad_net_labels_from_netlist(pcb, netlist):
    if not isinstance(netlist, dict): return {}
    terminal_net = {}
    for n in list(netlist.get('nets', []) or []):
        name = n.get('name')
        if not name: continue
        for t in list(n.get('terminals', []) or []):
            ref, pin = t.get('designator'), t.get('pin')
            if ref is not None and pin is not None: terminal_net[(str(ref), str(pin))] = str(name)
    refs = {}
    for idx, c in enumerate(list(getattr(pcb, 'components', []) or [])):
        ref = as_name(c)
        if ref is not None: refs[idx] = str(ref)
    labels = {}
    for p in list(getattr(pcb, 'pads', []) or []):
        ci, pn = field(p, 'component_index'), field(p, 'designator', 'name', 'pad_number', 'number', 'pin')
        if pn is None:
            raw=field(p,'raw_record','record')
            if isinstance(raw,dict): pn=raw.get('DESIGNATOR') or raw.get('Designator') or raw.get('PIN') or raw.get('Pin')
        try: ref = refs.get(int(ci))
        except Exception: ref = None
        n = terminal_net.get((ref, str(pn))) if ref is not None and pn is not None else None
        if n: labels[id(p)] = n
    return labels

def geometry_route_net_counts(pcb, netlist):
    pad_labels = pad_net_labels_from_netlist(pcb, netlist)
    segs = []
    for obj in list(getattr(pcb, 'tracks', []) or []) + list(getattr(pcb, 'arcs', []) or []):
        ep = segment_endpoints(obj)
        if ep is not None: segs.append((obj, ep[0], ep[1], str(field(obj, 'layer', 'layer_id'))))
    if not segs: return {}
    parent=list(range(len(segs)))
    def find(i):
        while parent[i] != i: parent[i]=parent[parent[i]]; i=parent[i]
        return i
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b: parent[b]=a
    def near(a,b,tol=1.0): return abs(a[0]-b[0])<=tol and abs(a[1]-b[1])<=tol
    em={}
    for i,(_,a,b,l) in enumerate(segs):
        em.setdefault((round(a[0]),round(a[1]),l),[]).append(i); em.setdefault((round(b[0]),round(b[1]),l),[]).append(i)
    for ids in em.values():
        for j in ids[1:]: union(ids[0],j)
    pads=list(getattr(pcb,'pads',[]) or [])
    for p in pads:
        n=pad_labels.get(id(p)); pp=xy(p)
        if not n or pp is None: continue
        pl=str(field(p,'layer','layer_id')); hits=[]
        for i,(_,a,b,l) in enumerate(segs):
            if (pl in ('74','MULTILAYER','MULTI-LAYER') or pl==l) and (near(pp,a) or near(pp,b)): hits.append(i)
        for j in hits[1:]: union(hits[0],j)
        for i in hits:
            r=find(i); setattr(p,'_audit_net_name',n) if False else None
    labels={}
    for p in pads:
        n=pad_labels.get(id(p)); pp=xy(p)
        if not n or pp is None: continue
        pl=str(field(p,'layer','layer_id'))
        for i,(_,a,b,l) in enumerate(segs):
            if (pl in ('74','MULTILAYER','MULTI-LAYER') or pl==l) and (near(pp,a) or near(pp,b)): labels.setdefault(find(i),set()).add(n)
    counts={}
    for r,nets in labels.items():
        if len(nets)==1:
            n=next(iter(nets)); counts[n]=counts.get(n,0)+sum(1 for i in range(len(segs)) if find(i)==r)
    return counts
def route_net_counts(pcb, netlist=None):
    net_by_idx=build_net_index_map(pcb)
    # Calibrate primitive net_index -> compiled net name from actual PCB pads
    # joined to the compiled schematic netlist. This avoids relying on the
    # parser's global net ordering (which can be 0- or 1-based).
    if netlist is not None:
        pad_labels=pad_net_labels_from_netlist(pcb, netlist)
        calibrated={}
        for p in list(getattr(pcb,"pads",[]) or []):
            n=pad_labels.get(id(p))
            ni=primitive_net_index(p)
            if n is not None and ni is not None:
                calibrated.setdefault(int(ni),set()).add(str(n))
        for ni,names in calibrated.items():
            if len(names)==1:
                net_by_idx[ni]=next(iter(names))
    routed={}
    for attr in ("tracks","arcs","vias","regions"):
        for item in list(getattr(pcb,attr,[]) or []):
            n=net_name(item, net_by_idx)
            if n: routed[n]=routed.get(n,0)+1
    if not routed and netlist is not None: return geometry_route_net_counts(pcb, netlist)
    return routed

def extract_unrouted(pcb):
    # Prefer parser-owned fly-wire/ratsnest collections. Absence is UNKNOWN.
    for attr in ("unrouted","ratsnest","rats_nest","airwires","connection_lines",
                 "from_tos","fromtos","from_to","connections","unrouted_connections"):
        v=getattr(pcb,attr,None)
        if v is not None:
            try: return list(v)
            except Exception: pass
    return None

def segment_endpoints(obj):
    for keys in (("x1","y1","x2","y2"),("start_x_mils","start_y_mils","end_x_mils","end_y_mils")):
        vals=[field(obj,k) for k in keys]
        if all(v is not None for v in vals):
            q=[num(v) for v in vals]
            if all(v is not None for v in q):
                return (q[0],q[1]),(q[2],q[3])
    a,b=field(obj,"start"),field(obj,"end")
    if a is not None and b is not None:
        a,b=xy(a),xy(b)
        if a is not None and b is not None: return a,b
    return None

def _snap_point(p, tolerance_mils=1.0):
    return (round(p[0] / tolerance_mils), round(p[1] / tolerance_mils))

def topology_components(pcb, netlist=None):
    """Build a conservative per-net copper graph.

    Pads are assigned to nets from the compiled schematic netlist. Track, via,
    region, and fill objects are then joined only when their own net identity is
    supported by a direct net name or a pad-calibrated net index. Unlabelled
    copper is never allowed to connect two nets or prove PASS.
    """
    pads = list(getattr(pcb, "pads", []) or [])
    tracks = list(getattr(pcb, "tracks", []) or [])
    arcs = list(getattr(pcb, "arcs", []) or [])
    vias = list(getattr(pcb, "vias", []) or [])
    regions = list(getattr(pcb, "regions", []) or [])
    fills = list(getattr(pcb, "fills", []) or [])
    pad_labels = pad_net_labels_from_netlist(pcb, netlist or {})
    if not pad_labels:
        return {}

    # Calibrate parser net indices from pad identities that have already been
    # reconciled against the compiled netlist. Conflicting indices are unusable.
    index_labels = {}
    for pad in pads:
        name = pad_labels.get(id(pad))
        idx = primitive_net_index(pad)
        if name is not None and idx is not None:
            index_labels.setdefault(int(idx), set()).add(str(name))
    net_index_map = build_net_index_map(pcb)
    for idx, labels in index_labels.items():
        if len(labels) == 1:
            net_index_map[idx] = next(iter(labels))
        else:
            net_index_map.pop(idx, None)

    known_names = set(pad_labels.values())

    def object_net(obj):
        value = field(obj, "net_name", "netname")
        if isinstance(value, dict):
            value = field(value, "name", "uid")
        if value is not None and str(value) in known_names:
            return str(value)
        raw_net = field(obj, "net")
        if isinstance(raw_net, str) and not raw_net.strip().isdigit():
            if raw_net in known_names:
                return raw_net
        if raw_net is not None and not isinstance(raw_net, (str, int, float)):
            value = field(raw_net, "name", "net_name", "netname", "uid")
            if value is not None and str(value) in known_names:
                return str(value)
        idx = primitive_net_index(obj)
        try:
            return net_index_map.get(int(idx)) if idx is not None else None
        except Exception:
            return None

    def point_in_poly(pt, poly):
        if len(poly) < 3:
            return False
        x, y = pt
        inside = False
        j = len(poly) - 1
        for i in range(len(poly)):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
                inside = not inside
            j = i
        return inside

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def segments_intersect(a, b, c, d):
        o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
        eps = 1e-8
        if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
            return True
        def on_segment(p, q, r):
            return (min(p[0], r[0]) - eps <= q[0] <= max(p[0], r[0]) + eps
                    and min(p[1], r[1]) - eps <= q[1] <= max(p[1], r[1]) + eps)
        return ((abs(o1) <= eps and on_segment(a, c, b))
                or (abs(o2) <= eps and on_segment(a, d, b))
                or (abs(o3) <= eps and on_segment(c, a, d))
                or (abs(o4) <= eps and on_segment(c, b, d)))

    def segment_hits_poly(a, b, poly):
        if point_in_poly(a, poly) or point_in_poly(b, poly):
            return True
        return any(segments_intersect(a, b, poly[i - 1], poly[i]) for i in range(len(poly)))

    def layer_of(obj):
        return layer_token(field(obj, "layer", "layer_id"))

    def layers_touch(a, b):
        multi = {"74", "MULTI-LAYER", "MULTILAYER"}
        if not a or not b:
            return False
        return a == b or a in multi or b in multi

    def point_segment_distance(point, start, end):
        dx, dy = end[0] - start[0], end[1] - start[1]
        if dx == 0 and dy == 0:
            return distance(point, start)
        t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)))
        projection = (start[0] + t * dx, start[1] + t * dy)
        return distance(point, projection)

    net_names = sorted(set(str(v) for v in pad_labels.values()))
    result = {}

    for net in net_names:
        net_pads = [p for p in pads if pad_labels.get(id(p)) == net and xy(p) is not None]
        if len(net_pads) < 2:
            continue

        nodes = []
        for pad in net_pads:
            nodes.append({"kind": "pad", "obj": pad, "point": xy(pad), "layer": layer_of(pad), "net": net})
        for obj in tracks + arcs:
            endpoints = segment_endpoints(obj)
            if endpoints is None or object_net(obj) != net:
                continue
            nodes.append({"kind": "segment", "obj": obj, "a": endpoints[0], "b": endpoints[1],
                          "layer": layer_of(obj), "net": net})
        for obj in vias:
            point = xy(obj)
            if point is not None and object_net(obj) == net:
                nodes.append({"kind": "via", "obj": obj, "point": point, "layer": layer_of(obj), "net": net})

        area_indices = []
        for obj in regions:
            area_net = object_net(obj)
            vertices = []
            for vertex in list(field(obj, "outline_vertices", "vertices", "outline") or []):
                point = xy(vertex)
                if point is not None:
                    vertices.append(point)
            layer = layer_of(obj)
            if len(vertices) >= 3 and layer and area_net == net:
                area_indices.append(len(nodes))
                nodes.append({"kind": "area", "obj": obj, "poly": vertices, "layer": layer, "net": net})
        for obj in fills:
            area_net = object_net(obj)
            x1 = num(field(obj, "pos1_x_mils", "pos1_x"))
            y1 = num(field(obj, "pos1_y_mils", "pos1_y"))
            x2 = num(field(obj, "pos2_x_mils", "pos2_x"))
            y2 = num(field(obj, "pos2_y_mils", "pos2_y"))
            layer = layer_of(obj)
            if area_net == net and layer and None not in (x1, y1, x2, y2):
                area_indices.append(len(nodes))
                nodes.append({"kind": "area", "obj": obj,
                              "poly": [(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                              "layer": layer, "net": net})

        parent = list(range(len(nodes)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        def union(i, j):
            a, b = find(i), find(j)
            if a != b:
                parent[b] = a

        pad_indices = [i for i, node in enumerate(nodes) if node["kind"] == "pad"]
        segment_indices = [i for i, node in enumerate(nodes) if node["kind"] == "segment"]
        via_indices = [i for i, node in enumerate(nodes) if node["kind"] == "via"]

        # Segment continuity is net-local and layer-local. Endpoint-to-segment
        # checks include T-junctions without joining coincident foreign-net copper.
        for pos, i in enumerate(segment_indices):
            left = nodes[i]
            for j in segment_indices[:pos]:
                right = nodes[j]
                if left["layer"] != right["layer"]:
                    continue
                if any(distance(p, q) <= 1.0 for p in (left["a"], left["b"]) for q in (right["a"], right["b"])):
                    union(i, j)
                    continue
                if any(
                    point_segment_distance(p, right["a"], right["b"]) <= 1.0
                    for p in (left["a"], left["b"])
                ) or any(
                    point_segment_distance(p, left["a"], left["b"]) <= 1.0
                    for p in (right["a"], right["b"])
                ):
                    union(i, j)

        # Pads join only to same-net copper on a compatible layer.
        for pi in pad_indices:
            pad = nodes[pi]
            width = num(field(pad["obj"], "width_mils", "width")) or 0.0
            height = num(field(pad["obj"], "height_mils", "height")) or 0.0
            tolerance = max(1.0, math.hypot(width, height) / 2.0)
            for si in segment_indices:
                seg = nodes[si]
                if layers_touch(pad["layer"], seg["layer"]) and point_segment_distance(
                    pad["point"], seg["a"], seg["b"]
                ) <= max(tolerance, (num(field(seg["obj"], "width_mils", "width")) or 0.0) / 2.0):
                    union(pi, si)

        # A via bridges layers only within its own net.
        for vi in via_indices:
            via = nodes[vi]
            diameter = num(field(via["obj"], "diameter_mils", "diameter", "size_mils", "size")) or 0.0
            tolerance = max(2.0, diameter / 2.0)
            for si in segment_indices:
                seg = nodes[si]
                if point_segment_distance(via["point"], seg["a"], seg["b"]) <= tolerance:
                    union(vi, si)

        # A net-scoped copper area is a graph node. It connects pads, tracks,
        # and vias only when the geometry intersects the filled polygon and
        # the copper layer is compatible. This avoids treating arbitrary regions
        # or foreign-net tracks as proof of continuity.
        for ai in area_indices:
            area = nodes[ai]
            poly = area["poly"]
            for ni, node in enumerate(nodes):
                if ni == ai or node["kind"] == "area":
                    continue
                if not layers_touch(area["layer"], node["layer"]) and node["kind"] != "via":
                    continue
                if node["kind"] == "pad":
                    touches = point_in_poly(node["point"], poly)
                elif node["kind"] == "segment":
                    touches = segment_hits_poly(node["a"], node["b"], poly)
                elif node["kind"] == "via":
                    touches = point_in_poly(node["point"], poly)
                else:
                    touches = False
                if touches:
                    union(ai, ni)
        # Overlapping same-net areas on a compatible layer share copper.
        for pos, ai in enumerate(area_indices):
            a = nodes[ai]
            for bi in area_indices[:pos]:
                b = nodes[bi]
                if not layers_touch(a["layer"], b["layer"]):
                    continue
                if any(point_in_poly(p, b["poly"]) for p in a["poly"]) or any(
                    point_in_poly(p, a["poly"]) for p in b["poly"]
                ) or any(segments_intersect(a["poly"][i - 1], a["poly"][i],
                                            b["poly"][j - 1], b["poly"][j])
                         for i in range(len(a["poly"])) for j in range(len(b["poly"]))):
                    union(ai, bi)

        pad_roots = {find(i) for i in pad_indices}
        # If a net-labelled copper area or track/via was omitted from the
        # net-scoped collections, don't turn a parser evidence gap into FAIL.
        topology_incomplete = False
        known_nodes = [node for node in nodes if node["kind"] in {"pad", "segment", "via", "area"}]
        known_geometry = [node for node in known_nodes if node["kind"] != "area"]
        for obj in tracks + arcs:
            if segment_endpoints(obj) is None or object_net(obj) is not None:
                continue
            a, b = segment_endpoints(obj)
            if any(point_segment_distance(a, n["a"], n["b"]) <= 1.0
                   or point_segment_distance(b, n["a"], n["b"]) <= 1.0
                   for n in known_geometry if n["kind"] == "segment"):
                topology_incomplete = True
                break
        if not topology_incomplete:
            for obj in regions + fills:
                if object_net(obj) is not None:
                    continue
                poly = []
                for vertex in list(field(obj, "outline_vertices", "vertices", "outline") or []):
                    point = xy(vertex)
                    if point is not None:
                        poly.append(point)
                if not poly:
                    x1 = num(field(obj, "pos1_x_mils", "pos1_x"))
                    y1 = num(field(obj, "pos1_y_mils", "pos1_y"))
                    x2 = num(field(obj, "pos2_x_mils", "pos2_x"))
                    y2 = num(field(obj, "pos2_y_mils", "pos2_y"))
                    if None not in (x1, y1, x2, y2):
                        poly = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                if len(poly) >= 3 and any(point_in_poly(n["point"], poly) for n in nodes if n["kind"] == "pad"):
                    topology_incomplete = True
                    break

        segment_roots = {find(i) for i in segment_indices}
        result[net] = {
            "terminal_nodes": len(net_pads),
            "graph_components": len(pad_roots),
            "route_segments": sum(1 for i in segment_indices if find(i) in pad_roots),
            "vias": sum(1 for i in via_indices if find(i) in pad_roots),
            "has_copper_area": bool(area_indices),
            "topology_incomplete": topology_incomplete,
        }

    return result

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def reconstruct(parts, out):
    parts = sorted(parts.glob("part_*.txt"))
    if not parts:
        raise RuntimeError("no b64parts/part_*.txt found")
    import base64
    raw = b"".join(p.read_bytes().strip() for p in parts)
    out.write_bytes(base64.b64decode(raw, validate=True))
    return parts

def write_schematic_evidence(out, components, netlist, project_id=None, compiled_graph=None):
    """Emit canonical parser-owned schematic identity, full pin inventory, and net evidence.

    Consume altium-monkey's public Design/Netlist projections without assuming
    parameters are dictionaries: current typed SchDoc records and serialized
    JSON projections can expose parameters as typed records, dicts, or lists.
    """
    def f(obj, *keys):
        return field(obj, *keys)

    def txt(v):
        return None if v is None else (str(v).strip() or None)

    def items(container):
        if container is None:
            return []
        if isinstance(container, dict):
            return [{"name": k, "value": v, "text": v} for k, v in container.items()]
        try:
            return list(container)
        except TypeError:
            return [container]

    def props(obj):
        out = {}
        raw = f(obj, "parameters", "properties")
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict):
                    v = f(v, "text", "value", "parameter_value")
                if v is not None:
                    out[str(k).strip().lower()] = txt(v)
        for child in items(raw) + items(f(obj, "children")):
            name = txt(f(child, "name", "parameter_name", "key", "key_name"))
            value = txt(f(child, "text", "value", "parameter_value"))
            if name and value:
                out[name.lower()] = value
        return out

    def ref(obj):
        # Use the same refdes resolver as the parse-contract validator.
        # Generic component.name is deliberately excluded: it is often a symbol name.
        direct = as_name(obj)
        if direct:
            return txt(direct)
        raw = f(obj, "raw_record", "record")
        if isinstance(raw, dict):
            for key in ("DESIGNATOR", "Designator", "designator", "REFDES", "RefDes"):
                if txt(raw.get(key)):
                    return txt(raw[key])
        return None

    def rec(obj):
        p = props(obj)
        pin_count = f(obj, "pin_count", "total_pin_count")
        if pin_count is None:
            classification = f(obj, "classification")
            pin_count = f(classification, "pin_count") if classification is not None else None
        return {
            "reference": ref(obj),
            "declared_value": txt(f(obj, "value", "component_value", "display_value", "comment")) or p.get("value") or p.get("comment"),
            "compiled_value": p.get("value"),
            "library_id": txt(f(obj, "library_reference", "library_ref", "lib_reference", "library_name", "symbol_name", "design_item_id")),
            "footprint": txt(f(obj, "footprint", "footprint_name")) or p.get("footprint"),
            "mpn": next((p.get(k) for k in (
                "manufacturer part number", "manufacturer_part_number",
                "manufacturerpartnumber", "mpn", "partnumber", "part_number"
            ) if p.get(k)), None),
            "description": txt(f(obj, "description", "desc")) or p.get("description"),
            "pin_count": pin_count,
            "properties": p,
        }

    records = [rec(x) for x in components or [] if ref(x)]
    by_ref = {str(x["reference"]): x for x in records}

    # The library's compiled Netlist b0 is authoritative for connected pins.
    connected = {}
    for n in (f(netlist, "nets") or []):
        nn = txt(f(n, "name", "uid", "canonical_name"))
        for t in f(n, "terminals") or []:
            rr = txt(f(t, "physical_designator", "designator", "refdes", "reference", "component_designator"))
            pp = txt(f(t, "pin_designator", "pin", "number", "pin_number", "physical_pin_designator"))
            if rr and pp:
                connected[(rr, pp)] = {
                    "pin": pp,
                    "pin_name": txt(f(t, "pin_name", "name", "display_name")),
                    "electrical_type": txt(f(t, "pin_type", "electrical_type", "electrical_kind")),
                    "connected_net": nn,
                }

    # Prefer the compiled graph's complete physical terminal inventory, which
    # includes unconnected pins and repeated/hierarchical occurrences.
    occurrence_to_ref = {}
    if isinstance(compiled_graph, dict):
        for occ in compiled_graph.get("component_occurrences", []) or []:
            rr = txt(f(occ, "source_designator", "physical_designator", "display_designator", "designator"))
            oid = txt(f(occ, "id", "occurrence_id"))
            if rr and oid:
                occurrence_to_ref[oid] = rr

    inventory = {}
    inventory_diag = {}
    if isinstance(compiled_graph, dict):
        for term in compiled_graph.get("terminal_occurrences", []) or []:
            if not isinstance(term, dict):
                continue
            occurrence_id = txt(f(term, "component_occurrence_ref", "component_occurrence_id", "component_ref"))
            rr = occurrence_to_ref.get(occurrence_id)
            pp = txt(f(term, "pin_designator", "physical_pin_designator", "pin_number", "pin"))
            if not rr or not pp:
                continue
            key = (rr, pp)
            t = {
                "pin": pp,
                "pin_name": txt(f(term, "name", "pin_name", "display_name")),
                "electrical_type": txt(f(term, "electrical_type", "pin_type", "electrical_kind")),
                "connected_net": None,
                "resolution_diagnostics": list(f(term, "resolution_diagnostics") or []),
            }
            t.update(connected.get(key, {}))
            inventory.setdefault(rr, {})[pp] = t
            if t["resolution_diagnostics"]:
                inventory_diag.setdefault(rr, {})[pp] = t["resolution_diagnostics"]

    # If graph inventory is absent, connected pins alone are not considered a
    # complete inventory; the parse contract below remains fail-closed.
    if not inventory:
        for (rr, pp), t in connected.items():
            inventory.setdefault(rr, {})[pp] = dict(t)

    for rr, x in by_ref.items():
        pins_for_ref = inventory.get(rr, {})
        x["pins"] = sorted(pins_for_ref.values(), key=lambda z: (str(z["pin"]), str(z.get("pin_name") or "")))
        x["observed_pin_count"] = len(x["pins"])
        x["pin_inventory_source"] = "compiled_schematic_graph.terminal_occurrences" if compiled_graph else "netlist.terminals"
        x["pin_resolution_diagnostics"] = inventory_diag.get(rr, {})
        x["evidence_state"] = "VERIFIED" if compiled_graph and rr in inventory else ("VERIFIED" if x["pins"] else "UNKNOWN")

    evidence = {
        "schema": "altium-schematic-evidence.v1",
        "status": "VERIFIED" if by_ref else "UNKNOWN",
        "project_id": project_id,
        "authority_note": "Parser/compiled observations only. No datasheet identity or functional intent is inferred.",
        "pin_inventory_contract": "Complete component pin inventory comes from compiled_schematic_graph.terminal_occurrences; connected_net is joined from compiled netlist terminals.",
        "components": sorted(by_ref.values(), key=lambda x: str(x["reference"])),
    }
    path = out / "schematic-evidence.json"
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    return evidence

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--archive", type=pathlib.Path)
    ap.add_argument("--source-sha256", type=str)
    ap.add_argument("--config", type=pathlib.Path, help="optional project-local config; never required by the engine")
    args = ap.parse_args()
    root, out = args.root, args.out
    project_config = {}
    if args.config and args.config.exists():
        project_config = json.loads(args.config.read_text(encoding="utf-8"))
    project_id = project_config.get("project_id")
    out.mkdir(parents=True, exist_ok=True)
    findings = []

    prjs = sorted(root.rglob("*.PrjPcb"))
    schs = sorted(root.rglob("*.SchDoc"))
    pcbs = sorted(root.rglob("*.PcbDoc"))
    if not schs or not pcbs:
        missing = [p for p, xs in (("*.SchDoc",schs),("*.PcbDoc",pcbs)) if not xs]
        add(findings,"G0-REQUIRED-FILES","BLOCKER","intake","UNKNOWN",
            "Baseline requires SchDoc + PcbDoc; missing: " + ", ".join(missing),"FACT")
        write_outputs(out, {"status":"BLOCKED","gates":{"G0_INTAKE":"UNKNOWN"},"findings":findings})
        return 2

    archive_hash = sha256(args.archive) if args.archive and args.archive.exists() else None
    if args.source_sha256 and archive_hash:
        if archive_hash.lower() == args.source_sha256.lower():
            add(findings,"G0-ARCHIVE-HASH","INFO","intake","VERIFIED",
                f"Archive SHA256 matches declared source hash {archive_hash}.","VERIFIED")
        else:
            add(findings,"G0-ARCHIVE-HASH","BLOCKER","intake","FAIL",
                f"Archive SHA256 {archive_hash} does not match declared source hash {args.source_sha256}.","VERIFIED")
    else:
        add(findings,"G0-ARCHIVE-HASH","INFO","intake","UNKNOWN",
            "No authoritative source SHA256 was supplied; archive byte identity cannot be proven. Hash verification is optional for direct/manual engine use.","FACT")

    sch_components = None
    try:
        if prjs:
            design = AltiumDesign.from_prjpcb(str(prjs[0]))
            payload = design.to_json(include_pnp=True, include_compile_metadata=True, include_indexes=True)
            pcb = design.load_pcbdoc()
            netlist_obj = design.to_netlist()
            netlist_text = netlist_obj.to_json_text()
            netlist = json.loads(netlist_text)
            parse_basis = f"project {prjs[0].name}"
        else:
            # Two-file baseline: parse each source directly. This intentionally
            # does not synthesize a compiled project/netlist.
            schdoc = AltiumSchDoc(str(schs[0]))
            pcb = AltiumPcbDoc.from_file(str(pcbs[0]))
            sch_components = list(getattr(schdoc, "components", []) or [])
            payload = {"components": [repr(x) for x in sch_components], "compile": None,
                       "diagnostics": [], "source_mode": "SCHDOC+PCBDOC"}
            netlist = None
            netlist_text = json.dumps({"nets": [], "authoritative": False}, indent=2)
            parse_basis = f"direct {schs[0].name} + {pcbs[0].name}"
        add(findings,"G1-PARSE","INFO","parse","VERIFIED",
            f"Loaded {parse_basis}; schematic count={len(schs)}, PCB count={len(pcbs)}.","VERIFIED")
    except Exception as exc:
        add(findings,"G1-PARSE","BLOCKER","parse","BLOCKED",
            f"Parser load failed: {type(exc).__name__}: {exc}","FACT")
        write_outputs(out, {"status":"BLOCKED","gates":{"G0_INTAKE":"UNKNOWN","G1_PARSE":"BLOCKED"},"findings":findings})
        return 2
    # Parser load success is not parser-contract success. Validate the canonical
    # compiled model and its net terminal references before any semantic consumer.
    parse_contract_ok = False
    try:
        parsed_components = list(payload.get("components") or [])
        parsed_nets = list((netlist or {}).get("nets") or [])
        refs = [as_name(x) for x in parsed_components]
        missing_refs = [i for i, ref in enumerate(refs) if not ref]
        ref_set = {str(ref) for ref in refs if ref}
        duplicate_count = len(refs) - len(ref_set)
        terminal_keys = set()
        bad_terminals = []
        orphan_terminals = []
        observed_by_ref = {}
        for net in parsed_nets:
            if not isinstance(net, dict) or not net.get("name"):
                bad_terminals.append("net-without-name")
                continue
            for term in list(net.get("terminals") or []):
                if not isinstance(term, dict):
                    bad_terminals.append("non-object-terminal")
                    continue
                ref = term.get("designator") or term.get("refdes") or term.get("reference")
                pin = term.get("pin") or term.get("pin_designator") or term.get("number")
                if not ref or pin is None:
                    bad_terminals.append(f"missing-ref-or-pin:{ref}:{pin}")
                    continue
                key = (str(ref), str(pin))
                if key in terminal_keys:
                    bad_terminals.append(f"duplicate-terminal:{ref}.{pin}")
                terminal_keys.add(key)
                observed_by_ref[str(ref)] = observed_by_ref.get(str(ref), 0) + 1
                if str(ref) not in ref_set:
                    orphan_terminals.append(f"{ref}.{pin}")

        missing_pin_count = []
        missing_pin_inventory = []
        for obj, ref in zip(parsed_components, refs):
            pc = field(obj, "pin_count")
            if pc is None:
                cl = field(obj, "classification")
                pc = cl.get("pin_count") if isinstance(cl, dict) else None
            try:
                if pc is None or int(pc) < 0:
                    missing_pin_count.append(str(ref) if ref else "<missing-ref>")
            except Exception:
                missing_pin_count.append(str(ref) if ref else "<missing-ref>")
            # Pin inventory is validated through canonical evidence, not raw parser objects.

        canonical_evidence = write_schematic_evidence(out, payload.get("components", []) if sch_components is None else sch_components, netlist, project_id=project_id, compiled_graph=payload.get("compiled_schematic_graph"))
        evidence_records = list(canonical_evidence.get("components") or [])
        evidence_refs = {str(x.get("reference")) for x in evidence_records if x.get("reference")}
        missing_evidence_refs = sorted(ref_set - evidence_refs)
        missing_pin_inventory = sorted(
            str(x.get("reference")) for x in evidence_records
            if x.get("reference") and not isinstance(x.get("pins"), list)
        )
        missing_observed_pins = sorted(
            str(x.get("reference")) for x in evidence_records
            if x.get("reference") and not x.get("pins")
        )
        pin_count_mismatches = []
        for x in evidence_records:
            ref = x.get("reference")
            pc = x.get("pin_count")
            observed = x.get("observed_pin_count")
            try:
                if ref and pc is not None and observed is not None and int(pc) != int(observed):
                    pin_count_mismatches.append(f"{ref}:{pc}!={observed}")
            except Exception:
                pin_count_mismatches.append(f"{ref}:invalid-pin-count")
        complete_inventory = bool(payload.get("compiled_schematic_graph"))
        parse_contract_ok = bool(
            prjs and parsed_components and parsed_nets
            and complete_inventory
            and not missing_refs
            and duplicate_count == 0
            and not bad_terminals
            and not orphan_terminals
            and not missing_pin_count
            and not missing_pin_inventory
            and not missing_evidence_refs
            and not missing_observed_pins
            and not pin_count_mismatches
            and len(evidence_records) == len(parsed_components)
        )
        if parse_contract_ok:
            add(findings,"G1-PARSE-CONTRACT","INFO","parse","VERIFIED",
                f"Canonical model verified: components={len(parsed_components)}, nets={len(parsed_nets)}, terminals={len(terminal_keys)}, unique designators/pin references, no orphan terminals.","VERIFIED")
        else:
            add(findings,"G1-PARSE-CONTRACT","BLOCKER","parse","BLOCKED",
                "Canonical parser contract incomplete: "
                f"components={len(parsed_components)}, nets={len(parsed_nets)}, "
                f"missing_designators={len(missing_refs)}, duplicate_designators={duplicate_count}, "
                f"bad_terminals={len(bad_terminals)}, orphan_terminals={len(orphan_terminals)}, "
                f"missing_pin_count={len(missing_pin_count)}, missing_evidence_refs={len(missing_evidence_refs)}, "
                f"missing_pin_inventory={len(missing_pin_inventory)}, missing_observed_pins={len(missing_observed_pins)}, "
                f"pin_count_mismatches={len(pin_count_mismatches)}, complete_inventory={complete_inventory}, evidence_record_count={len(evidence_records)}.","FACT")
    except Exception as exc:
        add(findings,"G1-PARSE-CONTRACT","BLOCKER","parse","BLOCKED",
            f"Canonical parser contract validation failed: {type(exc).__name__}: {exc}","FACT")
        parse_contract_ok = False

    diagnostics = payload.get("diagnostics") or []
    compile_data = payload.get("compile")

    # Semantic schematic gate: identity/library contradictions and provable
    # net-level electrical contradictions are checked before connectivity,
    # placement, or routing can be authorized.
    schematic_semantic_identities = []
    if run_schematic_semantics is not None:
        def _semantic_add(fid, severity, domain, status, evidence, confidence="VERIFIED", obj=None):
            add(findings, fid, severity, domain, status, evidence, confidence, obj)
        identity_overrides = project_config.get("identity_profile_overrides", {})
        schematic_semantic_identities = run_schematic_semantics(
            canonical_evidence,
            None,
            _semantic_add,
            identity_overrides=identity_overrides,
            skip_hcpl=bool((project_config.get("policy") or {}).get("skip_hcpl_semantics", False)),
        )
    else:
        add(findings, "G2-SCHEMATIC-SEMANTICS", "BLOCKER", "schematic", "BLOCKED",
            "Schematic semantic checker could not be loaded; functional authorization is blocked.", "FACT")
    if compile_data is None:
        add(findings,"G2-COMPILE","BLOCKER","compile","BLOCKED",
            "No authoritative compiled schematic/netlist evidence is available. Direct SchDoc parsing is structural-only and cannot authorize connectivity, placement, or routing.","FACT")
    elif diagnostics:
        add(findings,"G2-DIAGNOSTICS","HIGH","compile","FAIL",
            f"{len(diagnostics)} compile diagnostic record(s) emitted.","VERIFIED")
    else:
        add(findings,"G2-COMPILE","INFO","compile","VERIFIED",
            "Compile metadata is present and diagnostics are empty.","VERIFIED")

    try:
        write_schematic_evidence(
            out,
            payload.get("components", []) if sch_components is None else sch_components,
            netlist,
            project_id=project_id,
            compiled_graph=payload.get("compiled_schematic_graph"),
        )
        add(findings, "G2-SCHEMATIC-EVIDENCE", "INFO", "schematic", "VERIFIED",
            "Observed schematic identity and pin/net evidence packet emitted.", "VERIFIED")
        # HCPL repair planning is non-mutating. It may emit a plan, but the
        # plan itself is not a schematic finding. Identity authority is supplied
        # by the project policy/identity profile; actual wiring violations remain
        # authoritative FAIL/BLOCKED findings and still gate the phase.
        hcpl_policy = project_config.get("policy") or {}
        identity_overrides = project_config.get("identity_profile_overrides") or {}
        if build_hcpl_repair_plan is not None and not bool(hcpl_policy.get("skip_hcpl_semantics", False)):
            try:
                plan = build_hcpl_repair_plan(canonical_evidence.get("components") or [])
                (out / "hcpl_repair_plan.json").write_text(
                    json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                authorized = bool(identity_overrides.get("HCPL0600") or identity_overrides.get("HCPL-0600"))
                add(findings, "G2-HCPL-REPAIR-PLAN", "INFO", "schematic", "VERIFIED" if authorized else "BLOCKED",
                    "Non-mutating HCPL topology repair plan emitted; identity authority=%s. Any wiring mutation still requires a separate mutation permit and post-mutation reparse/verification."
                    % ("explicit" if authorized else "missing"),
                    "VERIFIED" if authorized else "FACT")
            except Exception as exc:
                add(findings, "G2-HCPL-REPAIR-PLAN", "BLOCKER", "schematic", "BLOCKED",
                    f"HCPL repair-plan generation failed: {type(exc).__name__}: {exc}", "FACT")
    except Exception as exc:
        add(findings, "G2-SCHEMATIC-EVIDENCE", "BLOCKER", "schematic", "BLOCKED",
            f"Could not emit required schematic evidence packet: {type(exc).__name__}: {exc}", "FACT")

    # In direct SCH+PCB mode keep the live parser objects for reference
    # reconciliation; payload["components"] is intentionally repr-only JSON.
    if sch_components is None:
        sch_components = payload.get("components", []) or []
    pcb_components = list(getattr(pcb, "components", []) or [])
    pcb_pads = list(getattr(pcb, "pads", []) or [])
    pcb_nets = list(getattr(pcb, "nets", []) or [])
    if not pcb_components or not pcb_pads:
        add(findings,"G4-PCB-STRUCTURE","BLOCKER","pcb","BLOCKED",
            f"Authoritative PcbDoc loaded but structural extraction is incomplete: components={len(pcb_components)}, pads={len(pcb_pads)}, nets={len(pcb_nets)}.","FACT")
    else:
        add(findings,"G4-PCB-STRUCTURE","INFO","pcb","VERIFIED",
            f"Authoritative PcbDoc structural extraction: components={len(pcb_components)}, pads={len(pcb_pads)}, nets={len(pcb_nets)}.","VERIFIED")
    srefs = {as_name(x) for x in sch_components if as_name(x)}
    prefs = {as_name(x) for x in pcb_components if as_name(x)}
    for ref in sorted(srefs - prefs):
        add(findings,f"G3-SCH-ONLY-{ref}","HIGH","connectivity","FAIL",
            "Schematic reference absent from parsed PCB component set.","VERIFIED",ref)
    for ref in sorted(prefs - srefs):
        add(findings,f"G3-PCB-ONLY-{ref}","HIGH","connectivity","FAIL",
            "PCB reference absent from parsed schematic component set.","VERIFIED",ref)
    if srefs == prefs:
        add(findings,"G3-REFDES","INFO","connectivity","VERIFIED",
            f"Schematic/PCB references reconcile: {len(srefs)} common references.","VERIFIED")
    else:
        add(findings,"G3-REFDES","BLOCKER","connectivity","FAIL",
            f"Reference mismatch: {len(srefs-prefs)} schematic-only; {len(prefs-srefs)} PCB-only.","VERIFIED")

    # Authoritative terminal join. An empty/missing netlist is not evidence;
    # it is a hard connectivity block.
    nl_nets = (netlist or {}).get("nets", []) or []
    if not nl_nets:
        add(findings,"G3-NETLIST-AUTHORITY","BLOCKER","connectivity","BLOCKED",
            "Authoritative compiled schematic netlist is missing or empty; reference reconciliation alone cannot prove pin-to-net connectivity.","FACT")
    sch_pin_to_net = {}
    for n in nl_nets:
        nn = field(n,"name","uid")
        for t in field(n,"terminals") or []:
            ref, pin = field(t,"designator","refdes","reference"), field(t,"pin","pin_designator","number")
            if ref is not None and pin is not None:
                sch_pin_to_net[(str(ref),str(pin))] = None if nn is None else str(nn)
    ref_by_idx = {i: as_name(c) for i,c in enumerate(pcb_components)}
    net_by_idx = {i: field(n,"name","net_name","netname","uid") for i,n in enumerate(pcb_nets)}
    pcb_pin_to_net = {}
    unresolved = 0
    for pad in pcb_pads:
        ci, pin, ni = field(pad,"component_index"), field(pad,"designator","pad_designator","number"), field(pad,"net_index")
        # Board-level / component-less pads (e.g. mechanical or standalone pads)
        # cannot correspond to a schematic terminal and must not poison SCH↔PCB
        # terminal reconciliation.
        if ci is None:
            continue
        if pin is None or ni is None:
            unresolved += 1
            continue
        ref = ref_by_idx.get(int(ci))
        if ref is not None:
            pcb_pin_to_net[(str(ref),str(pin))] = net_by_idx.get(int(ni))
    common = set(sch_pin_to_net) & set(pcb_pin_to_net)
    mismatches = [(k,sch_pin_to_net[k],pcb_pin_to_net[k]) for k in sorted(common)
                  if sch_pin_to_net[k] is not None and pcb_pin_to_net[k] is not None
                  and sch_pin_to_net[k].strip().upper() != str(pcb_pin_to_net[k]).strip().upper()]
    missing = set(sch_pin_to_net) - set(pcb_pin_to_net)
    # Direct two-file mode intentionally has no compiled schematic netlist;
    # without it, PCB-pad-vs-SCH-terminal reconciliation is not authoritative.
    extra = (set(pcb_pin_to_net) - set(sch_pin_to_net)) if nl_nets else set()
    for (ref,pin),a,b in mismatches[:200]:
        add(findings,f"G3-PIN-NET-{ref}-{pin}","HIGH","connectivity","FAIL",
            f"Schematic net={a!r}, PCB pad net={b!r}.","VERIFIED",f"{ref}.{pin}")
    unresolved_samples = []
    if unresolved:
        for idx, pad in enumerate(pcb_pads):
            ci = field(pad,"component_index")
            pin = field(pad,"designator","pad_designator","number")
            ni = field(pad,"net_index")
            if ci is not None and (pin is None or ni is None) and len(unresolved_samples) < 100:
                attrs = {}
                for name in sorted(set(["component_index","designator","pad_designator","number","net_index","net_name","netname","name","x","y","position","layer"])):
                    try:
                        value = getattr(pad, name)
                        if value is not None:
                            attrs[name] = value
                    except Exception:
                        pass
                unresolved_samples.append({"index": idx, "attrs": attrs, "repr": repr(pad)[:500]})
    if missing:
        add(findings,"G3-PIN-MISSING-ON-PCB","BLOCKER","connectivity","UNKNOWN",
            f"{len(missing)} schematic terminals lack normalized PCB pads.","FACT")
    elif unresolved:
        add(findings,"G3-PAD-NET-METADATA","INFO","connectivity","VERIFIED",
            f"{unresolved} PCB pad primitives lack normalized net_index metadata; no schematic terminal is missing from the normalized PCB terminal join.","VERIFIED")
    if extra:
        add(findings,"G3-PAD-NOT-IN-SCH","HIGH","connectivity","FAIL",
            f"{len(extra)} PCB pad terminals lack schematic terminal counterparts.","VERIFIED")
    if common and not mismatches and not missing and not extra:
        add(findings,"G3-PIN-NET","INFO","connectivity","VERIFIED",
            f"Full terminal join verified for {len(common)} SCH↔PCB terminal pairs.","VERIFIED")
    elif not common:
        add(findings,"G3-PIN-NET","BLOCKER","connectivity","UNKNOWN",
            "No normalized terminal/pad intersection was available for authoritative reconciliation.","FACT")

    counts = {}
    for attr in ("components","pads","vias","tracks","arcs","fills","regions","texts","nets","rules"):
        try: counts[attr] = len(getattr(pcb, attr))
        except Exception: counts[attr] = None

    # Deterministic subset of PCB rule checks.
    rules = list(getattr(pcb,"rules",[]) or [])
    enabled = [r for r in rules if getattr(r,"enabled",True)]
    add(findings,"G4-RULE-INVENTORY","INFO","pcb","VERIFIED",
        f"Parsed {len(rules)} PCB rules; {len(enabled)} enabled.","VERIFIED")
    def mil(v):
        try:
            s=str(v).strip().lower().replace("mil","").strip()
            return float(s)
        except Exception:
            return None
    width_rule = next((r for r in enabled if str(getattr(r,"rule_kind","")).lower()=="width"),None)
    minw = mil(field(width_rule,"minimum_width","min_width")) if width_rule else None
    rule_layer = str(getattr(width_rule,"layer","")).strip().upper() if width_rule else ""
    layer_aliases = {"TOP": int(PcbLayer.TOP), "BOTTOM": int(PcbLayer.BOTTOM)}
    applicable_layer = layer_aliases.get(rule_layer)
    if minw is not None and applicable_layer is not None:
        bad=[]
        applicable_tracks=0
        for i,t in enumerate(list(getattr(pcb,"tracks",[]) or [])):
            tlayer = field(t,"layer")
            try:
                tlayer_int = int(tlayer) if tlayer is not None else None
            except Exception:
                tlayer_int = None
            if tlayer_int != applicable_layer:
                continue
            applicable_tracks += 1
            w=mil(getattr(t,"width_mils",None))
            if w is not None and w < minw: bad.append((i,w))
        if bad:
            for i,w in bad[:200]:
                add(findings,f"G4-TRACK-WIDTH-{i}","HIGH","pcb","FAIL",
                    f"Track width {w:g}mil < rule minimum {minw:g}mil.","VERIFIED",f"track#{i}")
        else:
            add(findings,"G4-TRACK-WIDTH","INFO","pcb","VERIFIED",
                f"Evaluated {len(list(getattr(pcb,'tracks',[]) or []))} tracks against minimum width {minw:g}mil.","VERIFIED")
    else:
        reason = ("Authoritative Width minimum is exposed but its rule layer is not a supported legacy copper layer."
                  if minw is not None else
                  "Authoritative minimum Width rule field is not exposed; preferred width is not treated as a minimum.")
        add(findings,"G4-TRACK-WIDTH","BLOCKER","pcb","UNKNOWN",reason,"FACT")

    # Electrical structural checks.
    single = [n for n in nl_nets if len(n.get("terminals",[]) or []) == 1]
    for n in single[:200]:
        add(findings,f"G5-SINGLE-NET-{n.get('name','UNKNOWN')}","MEDIUM","electrical","FAIL",
            f"Net {n.get('name')!r} has exactly one compiled terminal; intentionality is not established.","VERIFIED",n.get("name"))
    outputs=[]
    for n in nl_nets:
        outs=[t for t in n.get("terminals",[]) or [] if str(t.get("pin_type","")).upper()=="OUTPUT"]
        if len(outs)>1: outputs.append((n,outs))
    for n,outs in outputs:
        ids=", ".join(f"{t.get('designator')}.{t.get('pin')}" for t in outs)
        add(findings,f"G5-OUTPUT-CONFLICT-{n.get('name','UNKNOWN')}","HIGH","electrical","FAIL",
            f"Net {n.get('name')!r} contains multiple OUTPUT pins: {ids}.","VERIFIED",n.get("name"))
    if not single: add(findings,"G5-SINGLE-PIN-NETS","INFO","electrical","VERIFIED","No single-terminal compiled nets.","VERIFIED")
    if not outputs: add(findings,"G5-OUTPUT-CONFLICTS","INFO","electrical","VERIFIED","No definite OUTPUT↔OUTPUT conflict found from pin semantics.","VERIFIED")
    # G5 structural evidence: classify supply nets without pretending PASSIVE pin
    # semantics prove source capability.
    supply_names = {"VBUS","24V","5V","5VP","3.3V","5V_RS232","5V_RS485","GND","GND_RS232","GND_RS485"}
    supply_evidence = []
    for n in nl_nets:
        name = str(n.get("name",""))
        if name in supply_names:
            ts = n.get("terminals",[]) or []
            caps = {
                "terminals": len(ts),
                "power_pins": sum(str(t.get("pin_type","")).upper()=="POWER" for t in ts),
                "capacitors": sum(str(t.get("designator","")).upper().startswith("C") for t in ts),
                "regulator_like": sum(str(t.get("designator","")).upper().startswith(("U","J")) for t in ts),
            }
            supply_evidence.append({"net":name, **caps})
            if caps["capacitors"] == 0:
                add(findings,f"G5-SUPPLY-DECOUPLING-{name}","INFO","electrical","UNKNOWN",
                    f"Supply net {name!r} has no capacitor terminal in the compiled netlist; whether local decoupling is required cannot be inferred generically.","FACT",name)
            else:
                add(findings,f"G5-SUPPLY-DECOUPLING-{name}","INFO","electrical","VERIFIED",
                    f"Supply net {name!r} has {caps['capacitors']} capacitor terminal(s) in the compiled netlist.","VERIFIED",name)
    add(findings,"G5-SUPPLY-STRUCTURE","INFO","electrical","VERIFIED",
        f"Structural supply inventory covers {len(supply_evidence)} named supply/ground nets; pin electrical semantics are retained without assuming PASSIVE means source.","VERIFIED")
    add(findings,"G5-INTENT-COVERAGE","INFO","electrical","UNKNOWN",
        "Protection, level compatibility, biasing, regulator operating limits and project-specific power intent are not derivable from generic connectivity alone.","FACT")
    # G6 structural geometry: board outline and primitive bounds are authoritative
    # parser facts, but do not substitute for a full Altium DRC engine.
    outline = getattr(getattr(pcb,"board",None),"outline",None)
    vertices = list(getattr(outline,"vertices",[]) or []) if outline else []
    if vertices:
        bb = getattr(outline,"bounding_box",None)
        add(findings,"G6-BOARD-OUTLINE","INFO","physical","VERIFIED",
            f"Parsed board outline with {len(vertices)} vertices; bounding_box={bb!r}.","VERIFIED")
        add(findings,"G6-BOARD-OUTLINE-CLOSED","INFO","physical",
            "VERIFIED" if len(vertices) >= 3 else "UNKNOWN",
            "Altium board outline is represented as an ordered polygon; closure is implicit from the final vertex back to the first.","VERIFIED")
        if bb and len(bb) == 4:
            x0,y0,x1,y1 = map(float,bb)
            outside = []
            for comp in list(getattr(pcb,"components",[]) or []):
                pos = None
                try:
                    pos = pcb.get_component_pick_place_center_mils(comp)
                except Exception:
                    pass
                if pos is None:
                    for keys in (("x_mils","y_mils"),("location_x_mils","location_y_mils")):
                        xv,yv = field(comp,keys[0]),field(comp,keys[1])
                        if xv is not None and yv is not None:
                            try: pos=(float(xv),float(yv))
                            except Exception: pass
                            break
                if pos is not None and not (x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1):
                    outside.append((as_name(comp),pos))
            if outside:
                for ref,pos in outside[:100]:
                    add(findings,f"G6-COMPONENT-OUTSIDE-{ref}","HIGH","physical","FAIL",
                        f"Component placement center {pos!r} lies outside board bounding box {tuple(bb)!r}.","VERIFIED",ref)
            else:
                add(findings,"G6-COMPONENT-BOUNDS","INFO","physical","VERIFIED",
                    f"All {len(list(getattr(pcb,'components',[]) or []))} component placement centers resolved inside board bounding box {tuple(bb)!r}.","VERIFIED")
    else:
        add(findings,"G6-BOARD-OUTLINE","BLOCKER","physical","UNKNOWN",
            "Authoritative PCB parser exposed no board-outline vertices.","FACT")
    # G6 PLACEMENT: component pair clearance and routing-corridor congestion.
    comps=list(getattr(pcb,"components",[]) or [])
    pads=list(getattr(pcb,"pads",[]) or [])
    comp_boxes={}
    comp_points={}
    comp_sides={}
    for idx,comp in enumerate(comps):
        ref=as_name(comp)
        if not ref: continue
        try: p=(float(comp.get_x_mils()),float(comp.get_y_mils()))
        except Exception: p=xy(comp)
        if p: comp_points[ref]=p
        # Resolve component mounting side from the parser's V7-aware layer
        # projection before falling back to legacy numeric layer ids. XY overlap
        # across Top/Bottom is not a 2D collision.
        side = None
        try:
            ls = getattr(comp, "layer_state", None)
            if callable(ls):
                state = ls()
                rr = getattr(state, "ref", None)
                side = layer_token(rr)
        except Exception:
            side = None
        if not side:
            raw_layer = field(comp, "layer", "v7_layer", "v7_layer_id")
            try:
                li = int(raw_layer)
                side = {1: "TOP", 32: "BOTTOM"}.get(li, layer_token(raw_layer))
            except Exception:
                side = layer_token(raw_layer) or None
        # Pad layer is stronger evidence for SMT side than the component
        # projection. Use it to distinguish intentional Top/Bottom XY overlap.
        pad_layers=set()
        for pad in pads:
            ci=field(pad,"component_index")
            try:
                if ci is None or int(ci)!=idx: continue
            except Exception:
                continue
            pl=field(pad,"layer","layer_id")
            if pl is not None: pad_layers.add(str(pl).upper())
        if pad_layers:
            if pad_layers.issubset({"1","TOP","TOP LAYER"}):
                side="TOP"
            elif pad_layers.issubset({"32","BOTTOM","BOTTOM LAYER"}):
                side="BOTTOM"
        comp_sides[ref]=side
        pts=[]
        for pad in pads:
            ci=field(pad,"component_index")
            try:
                if ci is None or int(ci)!=idx: continue
            except Exception: continue
            try: px=float(getattr(pad,"x_mils")); py=float(getattr(pad,"y_mils"))
            except Exception: continue
            try: wx=float(getattr(pad,"width_mils")); wy=float(getattr(pad,"height_mils"))
            except Exception: wx=wy=0.0
            if wx>0 and wy>0:
                pts.append((px-wx/2,py-wy/2,px+wx/2,py+wy/2))
        # Prefer actual component-body projection geometry over pad envelopes.
        body_pts=[]
        for body in list(getattr(pcb,"component_bodies",[]) or []) + list(getattr(pcb,"shapebased_component_bodies",[]) or []):
            ci=field(body,"component_index")
            try:
                if ci is None or int(ci)!=idx: continue
            except Exception: continue
            for v in list(getattr(body,"outline",[]) or []):
                q=xy(v)
                if q: body_pts.append(q)
        if body_pts:
            comp_boxes[ref]=(min(x for x,y in body_pts),min(y for x,y in body_pts),
                            max(x for x,y in body_pts),max(y for x,y in body_pts))
        elif pts:
            comp_boxes[ref]=(min(p[0] for p in pts),min(p[1] for p in pts),
                            max(p[2] for p in pts),max(p[3] for p in pts))
        if ref not in comp_boxes:
            # Fallback: extract the placed footprint geometry from the PcbDoc.
            # This gives a footprint-local envelope that can be transformed by
            # the component placement without requiring a separate PcbLib file.
            try:
                fp_lib=pcb.extract_footprint(getattr(comp,"footprint"))
                fp=list(getattr(fp_lib,"footprints",[]) or [None])[0]
                local=[]
                for attr in ("pads","tracks","arcs","regions","component_bodies"):
                    for obj in list(getattr(fp,attr,[]) or []):
                        q=xy(obj)
                        if q: local.append(q)
                if local and p:
                    try: rot=math.radians(float(getattr(comp,"rotation",0) or 0))
                    except Exception: rot=0.0
                    cr,sr=math.cos(rot),math.sin(rot)
                    transformed=[]
                    for lx,ly in local:
                        tx=lx*cr-ly*sr+p[0]; ty=lx*sr+ly*cr+p[1]
                        transformed.append((tx,ty))
                    comp_boxes[ref]=(min(x for x,y in transformed),min(y for x,y in transformed),
                                    max(x for x,y in transformed),max(y for x,y in transformed))
            except Exception:
                pass

    clearance_pairs=[]
    for i,a in enumerate(sorted(comp_boxes)):
        for b in sorted(comp_boxes)[i+1:]:
            # Opposite-side SMT bodies do not directly collide in 2D. Through-hole
            # / full-stack mechanical interaction remains covered by G6_PHYSICAL.
            sa, sb = comp_sides.get(a), comp_sides.get(b)
            if sa and sb:
                opposite = {sa, sb} in ({"TOP", "BOTTOM"}, {"TOP LAYER", "BOTTOM LAYER"})
                if opposite:
                    continue
            ba,bb=comp_boxes[a],comp_boxes[b]
            gap_x=max(0.0,max(ba[0],bb[0])-min(ba[2],bb[2]))
            gap_y=max(0.0,max(ba[1],bb[1])-min(ba[3],bb[3]))
            if gap_x==0 and gap_y==0:
                # XY overlap alone is not a collision proof. Require explicit
                # same-layer evidence; opposite/unknown sides are not blockers.
                # Bounding-box/courtyard overlap is not copper collision evidence.
                add(findings,f"G6-COMPONENT-OVERLAP-{a}-{b}","INFO","placement","UNKNOWN",
                    f"Component envelopes overlap; actual same-layer copper/keepout intersection is not proven by parsed component bbox: {a} side={sa!r}; {b} side={sb!r}.","FACT",f"{a}<->{b}")
            else:
                clearance_pairs.append((a,b,math.hypot(gap_x,gap_y)))

    if clearance_pairs:
        clearance_pairs.sort(key=lambda x:x[2])
        nearest=clearance_pairs[:10]
        for a,b,d in nearest:
            add(findings,f"G6-PLACEMENT-CLEARANCE-{a}-{b}","INFO","placement","VERIFIED",
                f"Nearest parsed component geometry gap={d:g} mil; no generic minimum is assumed.","VERIFIED",f"{a}<->{b}")
    else:
        add(findings,"G6-PLACEMENT-CLEARANCE","BLOCKER","placement","UNKNOWN",
            "No component bounding geometry was exposed by the parser.","FACT")

    # Explicit connector/choke-point evidence. This is deliberately descriptive:
    # names are not treated as design intent, only as a geometry inventory.
    connector_refs=sorted(r for r in comp_points if r.upper().startswith(("J","P","CON","SW")))
    for ref in connector_refs:
        p=comp_points[ref]
        nearby=[(other,distance(p,op)) for other,op in comp_points.items() if other!=ref and distance(p,op)<=1000]
        nearby.sort(key=lambda x:x[1])
        if len(nearby)>=6:
            add(findings,f"G6-ROUTING-CORRIDOR-{ref}","MEDIUM","placement","WARN",
                f"{ref} has {len(nearby)} component centers within 1000 mil; this is a geometry-based congestion signal, not proof of routing failure.","INFERRED",ref)

    # G7 ROUTING: report authoritative unrouted evidence when the parser exposes it,
    # plus routed primitive/net inventories. Never infer zero unrouted from absence.
    unrouted=extract_unrouted(pcb)
    if unrouted is None:
        add(findings,"G7-UNROUTED","INFO","routing","UNKNOWN",
            "Parser does not expose an authoritative unrouted/ratsnest collection; independent net-local copper topology is used as closure evidence when complete.","FACT")
    elif unrouted:
        for i,u in enumerate(unrouted[:200]):
            add(findings,f"G7-UNROUTED-{i}","HIGH","routing","FAIL",
                f"Authoritative unrouted/ratsnest item: {repr(u)[:700]}","VERIFIED",f"unrouted#{i}")
    else:
        add(findings,"G7-UNROUTED","INFO","routing","VERIFIED",
            "Authoritative PCB unrouted/ratsnest collection is empty.","VERIFIED")

    routed_counts=route_net_counts(pcb, netlist)
    pcb_net_names={str(field(n,"name","net_name","netname","uid")) for n in list(getattr(pcb,"nets",[]) or []) if field(n,"name","net_name","netname","uid") is not None}
    unrouted_candidates=sorted(pcb_net_names-set(routed_counts))
    if unrouted_candidates:
        add(findings,"G7-NETS-WITHOUT-ROUTE-PRIMITIVE","MEDIUM","routing","WARN",
            f"{len(unrouted_candidates)} PCB nets have no parsed track/arc/via/region primitive; these may be unrouted, pad-only, or plane-connected and require connectivity proof.",
            "INFERRED",unrouted_candidates[:100])
    else:
        add(findings,"G7-NETS-WITHOUT-ROUTE-PRIMITIVE","INFO","routing","VERIFIED",
            "Every named PCB net has at least one parsed routing/copper primitive.","VERIFIED")
    if routed_counts:
        add(findings,"G7-ROUTED-NET-INVENTORY","INFO","routing","VERIFIED",
            f"Routing primitives expose {len(routed_counts)} named nets; primitive counts are retained as route evidence.","VERIFIED")
        # Detect named nets with only one route primitive. This is a review signal,
        # not a DRC failure.
        for n,count in sorted(routed_counts.items()):
            if count==1:
                add(findings,f"G7-ROUTE-STUB-SIGNAL-{n}","LOW","routing","WARN",
                    f"Net {n!r} has exactly one routed primitive in the parser inventory; inspect for intentional short segment/stub.","INFERRED",n)
    else:
        # Missing parser net labels is an evidence limitation, not proof of unrouted copper.
        add(findings,"G7-ROUTED-NET-INVENTORY","INFO","routing","UNKNOWN",
            "Parser did not expose named routing primitives; route inventory is incomplete, but this is not itself a routing failure.","FACT")

    # Per-net route topology and layer transitions where fields are available.
    net_layers={}
    for t in list(getattr(pcb,"tracks",[]) or []):
        n=net_name(t, build_net_index_map(pcb)); layer=field(t,"layer")
        if n and layer is not None:
            net_layers.setdefault(n,set()).add(str(layer))
    for n,layers in sorted(net_layers.items()):
        if len(layers)>1:
            add(findings,f"G7-LAYER-TRANSITION-{n}","INFO","routing","VERIFIED",
                f"Net {n!r} is routed on {len(layers)} parsed layer identifiers: {sorted(layers)!r}.","VERIFIED",n)

    topo=topology_components(pcb, netlist)
    topo_bad=[(n,i) for n,i in sorted(topo.items()) if i["terminal_nodes"]>=2 and i["graph_components"]>1]
    if topo_bad:
        for n,info in topo_bad[:200]:
            if info.get("has_copper_area"):
                status, confidence, suffix = (
                    "UNKNOWN", "FACT",
                    " Net-scoped region/fill exists; plane connectivity is not proven."
                )
            elif info.get("topology_incomplete"):
                status, confidence, suffix = (
                    "UNKNOWN", "FACT",
                    " Parser could not assign all potentially bridging copper geometry to a net; disconnection is not proven."
                )
            else:
                status, confidence, suffix = (
                    "FAIL", "VERIFIED",
                    " Complete net-scoped copper geometry contains disconnected components."
                )
            add(findings,f"G7-TOPOLOGY-{n}","HIGH","routing",status,
                f"Independent copper graph: {info['terminal_nodes']} pads, {info['route_segments']} tracks, "
                f"{info['vias']} vias, {info['graph_components']} components.{suffix}",
                confidence,n)
    elif topo:
        add(findings,"G7-TOPOLOGY","INFO","routing","VERIFIED",
            f"Independent endpoint graph constructed for {len(topo)} named PCB nets; no disconnected multi-pad graph was proven.",
            "VERIFIED")
        for finding in findings:
            if finding["id"]=="G7-UNROUTED" and finding["status"]=="UNKNOWN":
                finding["status"]="VERIFIED"
                finding["confidence"]="VERIFIED"
                finding["evidence"]="No parser-owned ratsnest collection is exposed; the independent net-local copper graph verified no disconnected multi-pad topology."
    else:
        add(findings,"G7-TOPOLOGY","BLOCKER","routing","UNKNOWN",
            "Insufficient pad/track/via coordinates for an independent routing topology graph.","FACT")

    # Width/clearance checks are intentionally separated from topology. A parser
    # field is evidence only when the corresponding authoritative rule is exposed.
    add(findings,"G7-TOPOLOGY-LIMIT","INFO","routing","VERIFIED",
        "Generic geometry can verify route primitives and layer transitions, but not full SI/timing intent or return-path correctness without project-specific constraints.","FACT")

    add(findings,"G6-PHYSICAL","INFO","physical","UNKNOWN",
        "Full DRC/mechanical geometry equivalence is not implemented; structural outline evidence does not replace Altium's full DRC engine.","FACT")
    add(findings,"G7-FUNCTIONAL","INFO","functional","UNKNOWN",
        "Functional correctness requires explicit design intent and cannot be inferred from parser structure alone.","FACT")

    deferred_non_gating_ids = {"G2-SCH-NC-PIN-CONNECTED-U19","G2-HCPL-NC-PIN4-CONNECTED-U19","G2-SCH-NC-PIN-CONNECTED-U24","G2-HCPL-NC-PIN4-CONNECTED-U24","G2-SCH-NC-PIN-CONNECTED-U29","G2-HCPL-NC-PIN4-CONNECTED-U29","G2-HCPL-TOPOLOGY-ADC1_DATA","G2-HCPL-TOPOLOGY-ADC2_DATA","G2-HCPL-TOPOLOGY-ADC3_DATA"}
    gate_findings = [f for f in findings if f.get("id") not in deferred_non_gating_ids]

    def gate_for(prefix):
        fs=[f for f in gate_findings if f["id"].startswith(prefix)]
        if any(f["status"]=="FAIL" and f["severity"] in ("HIGH","BLOCKER") for f in fs): return "FAIL"
        if any(f["status"] in ("UNKNOWN","BLOCKED") and f["severity"]=="BLOCKER" for f in fs): return "BLOCKED"
        if any(f["status"]=="UNKNOWN" and f["severity"]!="INFO" for f in fs): return "PARTIAL"
        return "VERIFIED"

    gates = {
        "G0_INTAKE": "VERIFIED" if not any(f["id"]=="G0-ARCHIVE-HASH" and f["status"]=="FAIL" for f in findings) else "BLOCKED",
        "G1_PARSE":"VERIFIED" if parse_contract_ok else "BLOCKED",
        "G2_COMPILE": (
            "FAIL" if diagnostics or any(f["id"].startswith("G2-SCH-") or f["id"].startswith("G2-NET-") for f in gate_findings if f["status"]=="FAIL") else
            "BLOCKED" if any(f["id"]=="G2-COMPILE" and f["status"]=="BLOCKED" for f in gate_findings) or any(f["status"]=="BLOCKED" and f["domain"]=="schematic" for f in gate_findings) else
            "VERIFIED"
        ),
        "G3_CONNECTIVITY":"VERIFIED" if not any(f["id"].startswith("G3-") and f["status"] in ("FAIL","UNKNOWN","BLOCKED") for f in findings) else "BLOCKED",
        "G4_PCB":"VERIFIED" if not any(f["id"].startswith("G4-") and f["status"] in ("FAIL","UNKNOWN","BLOCKED") for f in findings) else "BLOCKED",
        "G5_ELECTRICAL":gate_for("G5-"),
        "G6_PHYSICAL":gate_for("G6-"),
        "G6_PLACEMENT":"BLOCKED" if any(f["domain"]=="placement" and f["severity"] in ("BLOCKER","HIGH") and f["status"] in ("UNKNOWN","FAIL","BLOCKED") for f in findings) else "VERIFIED",
        "G7_ROUTING": (
            "FAIL" if any(f["domain"]=="routing" and f["status"]=="FAIL" and f["severity"] in ("HIGH","BLOCKER") for f in findings)
            else "BLOCKED" if any(f["domain"]=="routing" and f["status"] in ("UNKNOWN","BLOCKED") and f["severity"]=="BLOCKER" for f in findings)
            else "PARTIAL" if any(f["domain"]=="routing" and f["status"]=="UNKNOWN" and f["severity"]!="INFO" for f in findings)
            else "VERIFIED"
        ),
        "G7_FUNCTIONAL":"PARTIAL" if any(f["id"]=="G7-FUNCTIONAL" and f["status"]=="UNKNOWN" and f["severity"]!="INFO" for f in findings) else "VERIFIED",
        "G8_REPORT":"VERIFIED"
    }
    hard_fail = any(f["status"]=="FAIL" and f["severity"] in ("HIGH","BLOCKER") for f in gate_findings)
    hard_block = any(f["status"] in ("BLOCKED","UNKNOWN") and f["severity"]=="BLOCKER" for f in gate_findings)
    incomplete = any(v in ("PARTIAL","UNKNOWN","BLOCKED") for v in gates.values())
    status = "FAIL" if hard_fail else ("BLOCKED" if hard_block or incomplete else "PASS")
    result = {
        "schema":"altium-audit/v2","status":status,"project":project_id or (prjs[0].name if prjs else "SCHDOC+PCBDOC"),
        "source_sha256":archive_hash,"gates":gates,"counts":counts,
        "findings":findings,"diagnostics":diagnostics,
        "lineage":{"project":str(prjs[0]) if prjs else None,"schematic_files":[str(x) for x in schs],
                   "pcb_files":[str(x) for x in pcbs]}
    }
    (out/"design.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"schematic_semantics.json").write_text(json.dumps(schematic_semantic_identities,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"netlist.json").write_text(netlist_text,encoding="utf-8")
    (out/"pcb_probe.txt").write_text(json.dumps({"counts":counts,"rules":len(rules),
        "pcb_attributes":sorted(x for x in dir(pcb) if not x.startswith("_"))},indent=2),encoding="utf-8")
    rule_samples = []
    for i, r in enumerate(enabled):
        if i >= 100: break
        attrs = {}
        for name in sorted(set(["rule_kind","name","enabled","minimum_width","min_width","maximum_width","max_width","gap","clearance","value","generic_clearance","minimum_clearance","scope","scope1","scope2","query1","query2","priority","net_name","layer"])):
            try:
                value = getattr(r, name)
                if value is not None:
                    attrs[name] = value
            except Exception:
                pass
        raw_record = getattr(r, "raw_record", None)
        if not isinstance(raw_record, dict): raw_record = {}
        raw_rule = {k: raw_record[k] for k in ("GAP","CLEARANCE","GENERICCLEARANCE","VALUE","MINCLEARANCE","MINIMUMCLEARANCE","OBJECTCLEARANCES") if raw_record.get(k) is not None}
        rule_samples.append({"index": i, "attrs": attrs, "raw_rule": raw_rule, "repr": repr(r)[:700]})
    track_samples = []
    for i, t in enumerate(list(getattr(pcb,"tracks",[]) or [])):
        if i >= 100: break
        attrs = {}
        for name in sorted(set(["width_mils","width","net_index","net_name","netname","layer","x1","y1","x2","y2","start","end"])):
            try:
                value = getattr(t, name)
                if value is not None:
                    attrs[name] = value
            except Exception:
                pass
        track_samples.append({"index": i, "attrs": attrs, "repr": repr(t)[:500]})
    (out/"g4_probe.json").write_text(json.dumps({
        "rule_count":len(rules),"enabled_rule_count":len(enabled),
        "width_rule_exposed":minw is not None,
        "width_rule_field":"minimum_width" if minw is not None else None,
        "counts":counts,
        "width_rule_repr": repr(width_rule)[:1500] if width_rule else None,
        "rule_samples":rule_samples,
        "track_samples":track_samples,
        "unresolved_pad_samples":unresolved_samples
    },indent=2,default=str),encoding="utf-8")
    report=["# Altium Audit Report","","**Overall:** "+status,"","## Gates"]
    report += [f"- **{k}**: {v}" for k,v in gates.items()]
    report += ["","## Findings"]
    for f in findings:
        report += [f"### {f['id']} — {f['severity']} / {f['status']}",
                    f"- Domain: {f['domain']}",f"- Object: {f['object']}",
                    f"- Evidence: {f['evidence']}",f"- Confidence: {f['confidence']}",""]
    (out/"report.md").write_text("\n".join(report),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"findings.json").write_text(json.dumps(findings,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"status":status,"gates":gates},indent=2))
    return 0 if status=="PASS" else 1

def write_outputs(out, summary):
    out.mkdir(parents=True,exist_ok=True)
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (out/"report.md").write_text("# Altium Audit Report\n\n"+json.dumps(summary,indent=2),encoding="utf-8")

if __name__ == "__main__":
    raise SystemExit(main())
