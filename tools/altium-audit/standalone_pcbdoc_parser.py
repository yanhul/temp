#!/usr/bin/env python3
"""Altium PcbDoc v6 parser and 2-layer routing analyzer.

Record layouts follow the user's supplied Reader/parse_track/parse_via/parse_pad/
parse_arc implementation. Connectivity is a geometric estimate, NOT Altium DRC.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, struct, time
from collections import defaultdict
from pathlib import Path
import olefile

ALT_U = 2.54e-6
NET_NONE = 0xFFFF
COMPONENT_NONE = 0xFFFF
LAYERS = {1:"Top",32:"Bottom",33:"TopOverlay",34:"BotOverlay",35:"TopPaste",36:"BotPaste",37:"TopSolder",38:"BotSolder",39:"Internal1",40:"Internal2",56:"KeepOut",74:"MultiLayer"}

class Reader:
    __slots__=("data","pos","error","sub_end")
    def __init__(self,data): self.data=data; self.pos=0; self.error=False; self.sub_end=None
    def remaining(self): return max(0,len(self.data)-self.pos)
    def _need(self,n):
        if n<0 or self.pos+n>len(self.data): self.error=True; return False
        return True
    def u8(self):
        if not self._need(1): return 0
        v=self.data[self.pos]; self.pos+=1; return v
    def u16(self):
        if not self._need(2): return 0
        v=struct.unpack_from("<H",self.data,self.pos)[0]; self.pos+=2; return v
    def u32(self):
        if not self._need(4): return 0
        v=struct.unpack_from("<I",self.data,self.pos)[0]; self.pos+=4; return v
    def i32(self):
        if not self._need(4): return 0
        v=struct.unpack_from("<i",self.data,self.pos)[0]; self.pos+=4; return v
    def f64(self):
        if not self._need(8): return 0.0
        v=struct.unpack_from("<d",self.data,self.pos)[0]; self.pos+=8; return v
    def skip(self,n):
        if not self._need(n): self.pos=len(self.data); return
        self.pos+=n
    def read_and_set_subrecord_len(self):
        n=self.u32(); self.sub_end=self.pos+n
        if self.sub_end>len(self.data): self.error=True; self.sub_end=len(self.data)
        return n
    def sub_remaining(self): return max(0,(self.sub_end if self.sub_end is not None else self.pos)-self.pos)
    def skip_subrecord(self):
        if self.sub_end is None or self.sub_end<self.pos or self.sub_end>len(self.data): self.error=True; return
        self.pos=self.sub_end
    def read_pascal_str(self):
        n=self.u8()
        if not self._need(n): return ""
        s=self.data[self.pos:self.pos+n].decode("latin-1",errors="replace"); self.pos+=n; return s
    def read_properties(self):
        n=self.u32(); binary=(n&0xff000000)!=0; n &= 0x00ffffff
        if n>self.remaining(): self.error=True; return {}
        raw=self.data[self.pos:self.pos+n]; self.pos+=n
        if binary or not n: return {}
        if raw.endswith(b"\0"): raw=raw[:-1]
        out={}
        for item in raw.decode("latin-1",errors="replace").split("|"):
            if "=" in item:
                k,v=item.split("=",1); out[k.strip().upper()]=v
        return out

def xy(r): return r.i32(),r.i32()
def parse_track(r):
    if r.u8()!=4: raise ValueError("Tracks6 recordtype mismatch")
    r.read_and_set_subrecord_len(); layer=r.u8(); flags1=r.u8(); flags2=r.u8(); net=r.u16(); r.u16(); comp=r.u16(); r.skip(4)
    x1,y1=xy(r); x2,y2=xy(r); width=r.i32(); r.u16(); r.skip(1); rem=r.sub_remaining()
    if rem>=9: r.skip(5); r.u32()
    if rem>=10: r.u8()
    r.skip_subrecord()
    if r.error: raise ValueError("truncated Tracks6 record")
    return dict(kind="track",layer=layer,net=net,component=comp,x1=x1,y1=y1,x2=x2,y2=y2,width=width,keepout=flags2==2)
def parse_via(r):
    if r.u8()!=3: raise ValueError("Vias6 recordtype mismatch")
    n=r.read_and_set_subrecord_len(); r.skip(1); f1=r.u8(); f2=r.u8(); net=r.u16(); r.skip(2); comp=r.u16(); r.skip(4)
    x,y=xy(r); dia=r.i32(); hole=r.i32(); start=r.u8(); end=r.u8()
    if n>74:
        r.skip(1); r.i32(); r.u8(); r.skip(1); r.i32(); r.i32(); r.i32(); r.skip(4); r.i32(); r.skip(8); r.u8(); r.u8(); r.skip(6); r.u8()
        for _ in range(32): r.i32()
    if n>=246: r.skip(38); r.u8(); r.i32()
    if n>=307: r.skip(45); r.i32(); r.i32()
    r.skip_subrecord()
    if r.error: raise ValueError("truncated Vias6 record")
    return dict(kind="via",net=net,component=comp,x=x,y=y,diameter=dia,hole=hole,start=start,end=end,tent_top=bool(f1&32),tent_bot=bool(f1&64))
def parse_pad(r):
    if r.u8()!=2: raise ValueError("Pads6 recordtype mismatch")
    r.read_and_set_subrecord_len(); name=r.read_pascal_str(); r.skip_subrecord()
    for _ in range(3): r.read_and_set_subrecord_len(); r.skip_subrecord()
    n=r.read_and_set_subrecord_len(); layer=r.u8(); f1=r.u8(); f2=r.u8(); net=r.u16(); r.skip(2); comp=r.u16(); r.skip(4)
    x,y=xy(r); tw,th,mw,mh,bw,bh=(r.i32() for _ in range(6)); hole=r.i32(); ts=r.u8(); ms=r.u8(); bs=r.u8(); rot=r.f64(); plated=r.u8(); r.skip(1); mode=r.u8(); r.skip(23); r.i32(); r.i32(); r.skip(7); r.u8(); r.u8(); r.skip(3)
    if n==110: r.skip(4)
    if n>=202: r.skip(40); r.i32(); r.skip(32); r.f64()
    r.skip_subrecord()
    n6=r.read_and_set_subrecord_len()
    if n6>=596:
        for _ in range(32): r.i32()
        for _ in range(32): r.i32()
        for _ in range(32): r.u8()
        r.skip(1); r.u8(); r.i32(); r.f64()
        for _ in range(32): r.i32()
        for _ in range(32): r.i32()
        r.skip(1)
        for _ in range(6): r.u8()
    r.skip_subrecord()
    if r.error: raise ValueError("truncated Pads6 record")
    return dict(kind="pad",name=name,layer=layer,net=net,component=comp,x=x,y=y,topw=tw,toph=th,midw=mw,midh=mh,botw=bw,both=bh,hole=hole,topshape=ts,botshape=bs,rot=rot,padmode=mode,plated=plated,tent_top=bool(f1&32),tent_bot=bool(f1&64))
def parse_arc(r):
    if r.u8()!=1: raise ValueError("Arcs6 recordtype mismatch")
    r.read_and_set_subrecord_len(); layer=r.u8(); f1=r.u8(); f2=r.u8(); net=r.u16(); r.u16(); comp=r.u16(); r.skip(4)
    cx,cy=xy(r); radius=r.i32(); sa=r.f64(); ea=r.f64(); width=r.i32(); r.u16(); rem=r.sub_remaining()
    if rem>=9: r.skip(1); r.skip(4); r.u32()
    if rem>=10: r.u8()
    r.skip_subrecord()
    if r.error: raise ValueError("truncated Arcs6 record")
    return dict(kind="arc",layer=layer,net=net,component=comp,cx=cx,cy=cy,radius=radius,sa=sa,ea=ea,width=width,keepout=f2==2)
def parse_props(data):
    r=Reader(data); out=[]
    while r.remaining()>=4:
        before=r.pos; p=r.read_properties()
        if r.error or r.pos<=before: break
        out.append(p)
    return out
def parse_unit(v,default=0.0):
    if v is None:return default
    s=str(v).strip()
    try:
        if s.endswith("mil"):return float(s[:-3])*10000
        if s.endswith("mm"):return float(s[:-2])/ALT_U
        if s.endswith("cm"):return float(s[:-2])/(2.54e-5)
        if s.endswith("in"):return float(s[:-2])*1000000
        return float(s)
    except ValueError:return default
def records(data,fn,label):
    r=Reader(data); out=[]; errors=[]
    while r.remaining()>=5:
        start=r.pos
        try:
            out.append(fn(r))
            if r.pos<=start: raise ValueError("parser made no progress")
        except Exception as e:
            errors.append({"offset":start,"error":str(e),"remaining":r.remaining()}); break
    return out,errors
def parse_regions(data):
    out=[]; r=Reader(data)
    while r.remaining()>=5:
        start=r.pos
        try:
            rt=r.u8(); r.read_and_set_subrecord_len(); layer=r.u8(); r.u8(); r.u8(); r.u16(); r.u16(); r.u16(); r.skip(5); r.u16(); r.skip(2); props=r.read_properties(); n=r.u32()
            if n>100000 or n*16>r.sub_remaining(): raise ValueError("invalid region vertex count")
            pts=[(r.f64(),r.f64()) for _ in range(n)]; r.skip_subrecord()
            out.append({"recordtype":rt,"name":props.get("NAME","?"),"kind":props.get("KIND","?"),"layer":layer,"vertices":pts})
        except Exception: r.pos=start; break
    return out
def parse_dimensions(data):
    out=[]; r=Reader(data)
    while r.remaining()>=6:
        r.skip(2); p=r.read_properties()
        if r.error or not p: break
        out.append({"kind":p.get("DIMENSIONKIND",""),"layer":p.get("LAYER",""),"x1":parse_unit(p.get("X1")),"y1":parse_unit(p.get("Y1")),"x2":parse_unit(p.get("X2")),"y2":parse_unit(p.get("Y2")),"prefix":p.get("TEXTPREFIX",""),"suffix":p.get("TEXTSUFFIX",""),"unit":p.get("TEXTDIMENSIONUNIT","Millimeters")})
    return out
def u2mm(u): return u*ALT_U
def mil(u): return round(u/10000,2)
def layer_name(x): return LAYERS.get(x,("Mech%d"%x if 57<=x<=88 else str(x)))
def net_name(pcb,n): return "(no net)" if n==NET_NONE else (pcb["nets"][n] if n<len(pcb["nets"]) else "Net#%d"%n)
def load_pcbdoc(path):
    path=Path(path)
    if not path.is_file(): raise FileNotFoundError(path)
    ole=olefile.OleFileIO(str(path))
    try:
        streams={}
        for parts in ole.listdir(streams=True,storages=False):
            try: streams["/".join(parts)]=ole.openstream(parts).read()
            except Exception: pass
    finally: ole.close()
    def stream(k): return streams.get(k,b"")
    bprops=Reader(stream("Board6/Data")).read_properties()
    outline=[]; i=0
    while f"VX{i}" in bprops and f"VY{i}" in bprops:
        outline.append((int(parse_unit(bprops[f"VX{i}"])),int(parse_unit(bprops[f"VY{i}"])))); i+=1
    pcb={"board_props":bprops,"outline":outline,"origin":(int(parse_unit(bprops.get("ORIGINX"))),int(parse_unit(bprops.get("ORIGINY")))),"layercount":int(float(bprops.get("LAYERSETSCOUNT","1")))+1}
    pcb["nets"]=[p.get("NAME","") for p in parse_props(stream("Nets6/Data"))]
    pcb["components"]=parse_props(stream("Components6/Data"))
    pcb["tracks"],te=records(stream("Tracks6/Data"),parse_track,"Tracks6")
    pcb["vias"],ve=records(stream("Vias6/Data"),parse_via,"Vias6")
    pcb["pads"],pe=records(stream("Pads6/Data"),parse_pad,"Pads6")
    pcb["arcs"],ae=records(stream("Arcs6/Data"),parse_arc,"Arcs6")
    pcb["parse_errors"]={"tracks":te,"vias":ve,"pads":pe,"arcs":ae}
    pcb["rules"]=[]
    rr=Reader(stream("Rules6/Data"))
    while rr.remaining()>=6:
        rr.skip(2); p=rr.read_properties()
        if rr.error: break
        pcb["rules"].append(p)
    pcb["classes"]=parse_props(stream("Classes6/Data"))
    pcb["board_regions"]=parse_regions(stream("BoardRegions/Data"))
    pcb["dimensions"]=parse_dimensions(stream("Dimensions6/Data"))
    xs=[p[0] for p in outline]; ys=[p[1] for p in outline]
    shape=(min(xs),min(ys),max(xs),max(ys)) if xs else None
    kx=[]; ky=[]
    for t in pcb["tracks"]:
        if t["layer"]==56: kx += [t["x1"],t["x2"]]; ky += [t["y1"],t["y2"]]
    for a in pcb["arcs"]:
        if a["layer"]==56: kx += [a["cx"]-a["radius"],a["cx"]+a["radius"]]; ky += [a["cy"]-a["radius"],a["cy"]+a["radius"]]
    ko=(min(kx),min(ky),max(kx),max(ky)) if kx else None
    dx=[]; dy=[]
    for d in pcb["dimensions"]:
        x=abs(d["x2"]-d["x1"]); y=abs(d["y2"]-d["y1"]); span=max(x,y)
        if span and min(x,y)<=.005*span: (dx if x>=y else dy).append(span)
    # Prefer the native Board6 outline vertices when present. KeepOut is only
    # a fallback because its bounding box is not necessarily the routed board edge.
    board_poly=pcb["outline"] if len(pcb["outline"]) >= 3 else []
    if board_poly:
        ox=[p[0] for p in board_poly]; oy=[p[1] for p in board_poly]
        border=(min(ox),min(oy),max(ox),max(oy)); source="Board6 native outline vertices"
    else:
        border=ko or ((0,0,max(dx),max(dy)) if dx and dy else None)
        source="KeepOut bbox (fallback; not verified outline)" if ko else ("dimension annotations (fallback; not verified outline)" if border else None)
    pcb["true_outline"]={"border":border,"border_source":source,"outline_polygon":board_poly,"shape_region":shape,"dim_x_mm":u2mm(max(dx)) if dx else None,"dim_y_mm":u2mm(max(dy)) if dy else None}
    pcb["streams"]={k:{"size_bytes":len(v),"sha256":hashlib.sha256(v).hexdigest()} for k,v in streams.items()}
    pcb["source"]={"path":str(path),"size_bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    return pcb
def pad_bbox(p):
    if p["layer"]==1:w,h=p["topw"],p["toph"]
    elif p["layer"]==32:w,h=p["botw"],p["both"]
    else:w,h=max(p["topw"],p["botw"]),max(p["toph"],p["both"])
    return p["x"]-w/2,p["y"]-h/2,p["x"]+w/2,p["y"]+h/2
def point_seg_dist(x1,y1,x2,y2,x,y):
    dx=x2-x1; dy=y2-y1; ll=dx*dx+dy*dy
    t=max(0,min(1,((x-x1)*dx+(y-y1)*dy)/ll)) if ll else 0
    return math.hypot(x-(x1+t*dx),y-(y1+t*dy))
class DSU:
    def __init__(self):self.p={}
    def find(self,x):
        self.p.setdefault(x,x)
        if self.p[x]!=x:self.p[x]=self.find(self.p[x])
        return self.p[x]
    def union(self,a,b):
        a=self.find(a); b=self.find(b)
        if a!=b:self.p[a]=b
def analyze_connectivity(pcb):
    """Heuristic geometry connectivity; not equivalent to Altium's connectivity engine."""
    bypad=defaultdict(list); bytrack=defaultdict(list); byvia=defaultdict(list)
    for i,p in enumerate(pcb["pads"]):
        if p["net"]!=NET_NONE:bypad[p["net"]].append(i)
    for i,t in enumerate(pcb["tracks"]):
        if t["net"]!=NET_NONE and t["layer"] in (1,32):bytrack[t["net"]].append(i)
    for i,v in enumerate(pcb["vias"]):
        if v["net"]!=NET_NONE:byvia[v["net"]].append(i)
    out={}
    for n in sorted(set(bypad)|set(bytrack)|set(byvia)):
        d=DSU(); pads=bypad[n]; tracks=bytrack[n]; vias=byvia[n]
        for i in pads:d.find("P"+str(i))
        for i in tracks:d.find("T"+str(i))
        for i in vias:d.find("V"+str(i))
        ends=defaultdict(list)
        for i in tracks:
            t=pcb["tracks"][i]
            ends[(t["layer"],t["x1"],t["y1"])].append(i); ends[(t["layer"],t["x2"],t["y2"])].append(i)
        for ids in ends.values():
            for i in ids[1:]:d.union("T"+str(ids[0]),"T"+str(i))
        segs=[(i,pcb["tracks"][i]) for i in tracks]
        for pos,(i,t) in enumerate(segs):
            for j,s in segs[pos+1:]:
                if t["layer"]==s["layer"] and (point_seg_dist(s["x1"],s["y1"],s["x2"],s["y2"],t["x1"],t["y1"])<=max(t["width"],s["width"])/2+1 or point_seg_dist(s["x1"],s["y1"],s["x2"],s["y2"],t["x2"],t["y2"])<=max(t["width"],s["width"])/2+1 or point_seg_dist(t["x1"],t["y1"],t["x2"],t["y2"],s["x1"],s["y1"])<=max(t["width"],s["width"])/2+1 or point_seg_dist(t["x1"],t["y1"],t["x2"],t["y2"],s["x2"],s["y2"])<=max(t["width"],s["width"])/2+1):d.union("T"+str(i),"T"+str(j))
        for vi in vias:
            v=pcb["vias"][vi]
            for ti,t in segs:
                if point_seg_dist(t["x1"],t["y1"],t["x2"],t["y2"],v["x"],v["y"])<=v["diameter"]/2+t["width"]/2:d.union("V"+str(vi),"T"+str(ti))
            for pi in pads:
                p=pcb["pads"][pi]; b=pad_bbox(p)
                if b[0]-v["diameter"]/2<=v["x"]<=b[2]+v["diameter"]/2 and b[1]-v["diameter"]/2<=v["y"]<=b[3]+v["diameter"]/2:d.union("V"+str(vi),"P"+str(pi))
        for ti,t in segs:
            bwidth=t["width"]/2
            for pi in pads:
                p=pcb["pads"][pi]; b=pad_bbox(p)
                for x,y in ((t["x1"],t["y1"]),(t["x2"],t["y2"])):
                    if b[0]-bwidth<=x<=b[2]+bwidth and b[1]-bwidth<=y<=b[3]+bwidth:d.union("P"+str(pi),"T"+str(ti)); break
        groups=defaultdict(list)
        for key in list(d.p):groups[d.find(key)].append(key)
        pg=[sorted(int(x[1:]) for x in g if x.startswith("P")) for g in groups.values()]
        pg=[g for g in pg if g]
        out[n]={"name":net_name(pcb,n),"n_pads":len(pads),"n_tracks":len(tracks),"n_vias":len(vias),"n_groups":len(pg),"pad_groups":pg}
    return out
def build_report(pcb,file_path,conn=None,full=False):
    t=pcb["true_outline"]; report={"file":str(file_path),"format":"Altium PcbDoc (binary v6)","source":pcb["source"],"streams":pcb["streams"],"board":{},"counts":{"nets":len(pcb["nets"]),"components":len(pcb["components"]),"pads":len(pcb["pads"]),"tracks":len(pcb["tracks"]),"vias":len(pcb["vias"]),"arcs":len(pcb["arcs"]),"rules":len(pcb["rules"])},"stackup":{"copper_layers":pcb["layercount"],"note":"LAYERSETSCOUNT+1 as stored; electrical copper = Top + Bottom"},"parse_errors":pcb["parse_errors"]}
    if t["border"]:
        b=t["border"]; report["board"]={"size_mm":[round(u2mm(b[2]-b[0]),2),round(u2mm(b[3]-b[1]),2)],"outline_bbox_mm":[round(u2mm(v),2) for v in b],"outline_source":t["border_source"],"dimension_annotations_mm":[round(t["dim_x_mm"],2),round(t["dim_y_mm"],2)] if t["dim_x_mm"] and t["dim_y_mm"] else None}
    if t["shape_region"]:
        s=t["shape_region"]; report["board"]["board_shape_region_bbox_mm"]=[round(u2mm(s[2]-s[0]),2),round(u2mm(s[3]-s[1]),2)]
    report["board"]["outline_verified"] = bool(t.get("outline_polygon") and len(t["outline_polygon"]) >= 3)
    report["board"]["outline_vertex_count"] = len(t.get("outline_polygon", []))
    # Component body/courtyard geometry is not present in the parsed component
    # property records. Report pad-envelope edge clearance as a screening metric,
    # never as proof that component bodies fit or do not collide.
    by_component=defaultdict(list)
    for p in pcb["pads"]:
        if p["component"] != COMPONENT_NONE and p["component"] < len(pcb["components"]):
            b=pad_bbox(p); by_component[p["component"]].append((b,p))
    if t["border"]:
        bx1,by1,bx2,by2=t["border"]
        edge_rows=[]
        for ci,items in by_component.items():
            boxes=[b for b,p in items]
            x1=min(b[0] for b in boxes); y1=min(b[1] for b in boxes)
            x2=max(b[2] for b in boxes); y2=max(b[3] for b in boxes)
            edge=min(x1-bx1,y1-by1,bx2-x2,by2-y2)
            c=pcb["components"][ci]
            edge_rows.append({"component_index":ci,"designator":c.get("SOURCEDESIGNATOR","?"),"pad_envelope_edge_clearance_mm":round(u2mm(edge),3)})
        edge_rows.sort(key=lambda x:x["pad_envelope_edge_clearance_mm"])
        report["placement_screen"]={"method":"axis-aligned pad envelope against board-outline bounding box; not body/courtyard DRC","component_count_with_pads":len(edge_rows),"components_with_pad_envelope_within_3mm_of_bbox_edge":[x for x in edge_rows if x["pad_envelope_edge_clearance_mm"] < 3],"components_with_pad_envelope_outside_bbox":[x for x in edge_rows if x["pad_envelope_edge_clearance_mm"] < 0],"body_collision_check":"NOT_PERFORMED: footprint body/courtyard geometry is not decoded by this parser"}
    tl=sum(math.hypot(x["x2"]-x["x1"],x["y2"]-x["y1"]) for x in pcb["tracks"] if x["layer"]==1); bl=sum(math.hypot(x["x2"]-x["x1"],x["y2"]-x["y1"]) for x in pcb["tracks"] if x["layer"]==32)
    report["copper"]={"top_length_mm":round(u2mm(tl),1),"bottom_length_mm":round(u2mm(bl),1),"track_widths_mil":sorted({mil(x["width"]) for x in pcb["tracks"] if x["layer"] in (1,32)}),"vias":[{"diameter_mil":mil(v["diameter"]),"hole_mil":mil(v["hole"]),"x_mm":round(u2mm(v["x"]),3),"y_mm":round(u2mm(v["y"]),3),"net":net_name(pcb,v["net"])} for v in pcb["vias"]]}
    report["rules"]=[{k:p.get(k) for k in ("RULEKIND","NAME","GAP","MINLIMIT","MAXLIMIT","PREFEREDWIDTH","PREFERREDWIDTH") if p.get(k) not in (None,"-")} for p in pcb["rules"] if p.get("RULEKIND") in ("Clearance","Width","RoutingVias")]
    if conn is not None:
        unr={k:v for k,v in conn.items() if v["n_groups"]>1}
        report["routing_analysis"]={"method":"geometric heuristic; not Altium DRC/connectivity proof","connectivity_verified":False,"nets_total":len(conn),"nets_fully_routed_estimate":len(conn)-len(unr),"nets_unrouted_or_partial_estimate":len(unr),"total_airwires_estimate":sum(v["n_groups"]-1 for v in unr.values()),"unrouted_nets":{net_name(pcb,k):{"pads":v["n_pads"],"groups":v["n_groups"],"tracks":v["n_tracks"],"vias":v["n_vias"],"pad_groups":[{"pad_ids":g,"x_mm":round(u2mm(pcb["pads"][g[0]]["x"]),3),"y_mm":round(u2mm(pcb["pads"][g[0]]["y"]),3)} for g in v["pad_groups"] if g]} for k,v in unr.items()}}
    if full:
        def desig(i):return pcb["components"][i].get("SOURCEDESIGNATOR","?") if i<len(pcb["components"]) else "?"
        report["primitives"]={"pads":[{"name":p["name"],"component_index":p["component"],"designator":desig(p["component"]) if p["component"]!=COMPONENT_NONE else None,"net":net_name(pcb,p["net"]),"layer":layer_name(p["layer"]),"x_mm":round(u2mm(p["x"]),3),"y_mm":round(u2mm(p["y"]),3),"top_size_mm":[round(u2mm(p["topw"]),3),round(u2mm(p["toph"]),3)],"bottom_size_mm":[round(u2mm(p["botw"]),3),round(u2mm(p["both"]),3)],"hole_mm":round(u2mm(p["hole"]),3),"rotation_deg":p["rot"]} for p in pcb["pads"]],"tracks":[{"layer":layer_name(x["layer"]),"net":net_name(pcb,x["net"]),"x1_mm":round(u2mm(x["x1"]),3),"y1_mm":round(u2mm(x["y1"]),3),"x2_mm":round(u2mm(x["x2"]),3),"y2_mm":round(u2mm(x["y2"]),3),"width_mm":round(u2mm(x["width"]),4)} for x in pcb["tracks"] if x["layer"] in (1,32)],"vias":report["copper"]["vias"],"arcs":[{"layer":layer_name(x["layer"]),"net":net_name(pcb,x["net"]),"cx_mm":round(u2mm(x["cx"]),3),"cy_mm":round(u2mm(x["cy"]),3),"radius_mm":round(u2mm(x["radius"]),3),"start_angle_deg":x["sa"],"end_angle_deg":x["ea"],"width_mm":round(u2mm(x["width"]),4)} for x in pcb["arcs"] if x["layer"] in (1,32)],"components":[{"designator":c.get("SOURCEDESIGNATOR","?"),"pattern":c.get("PATTERN","?"),"layer":c.get("LAYER","?"),"x_mm":round(u2mm(parse_unit(c.get("X"))),3),"y_mm":round(u2mm(parse_unit(c.get("Y"))),3),"rotation_deg":float(c.get("ROTATION",0) or 0)} for c in pcb["components"]]}
    return report
def main():
    ap=argparse.ArgumentParser(description="Parse Altium PcbDoc binary v6 -> JSON and estimated 2-layer routing analysis")
    ap.add_argument("file"); ap.add_argument("-o","--output"); ap.add_argument("--no-analysis",action="store_true"); ap.add_argument("--full",action="store_true")
    a=ap.parse_args()
    if not os.path.isfile(a.file): ap.error("Không tìm thấy file: %s"%a.file)
    t0=time.time(); pcb=load_pcbdoc(a.file)
    print("=== TỔNG QUAN ===")
    for label,key in (("Nets","nets"),("Components","components"),("Pads","pads"),("Tracks","tracks"),("Vias","vias"),("Arcs","arcs")):print(f"{label:12}: {len(pcb[key])}")
    b=pcb["true_outline"]["border"]
    if b:print("Kích thước board: %.2f x %.2f mm (nguồn: %s)"%(u2mm(b[2]-b[0]),u2mm(b[3]-b[1]),pcb["true_outline"]["border_source"]))
    conn=None
    if not a.no_analysis:
        conn=analyze_connectivity(pcb); unr={k:v for k,v in conn.items() if v["n_groups"]>1}
        print("Nets analyzed:",len(conn)," partial/unrouted estimate:",len(unr)," airwire estimate:",sum(v["n_groups"]-1 for v in unr.values()))
    out=a.output or os.path.splitext(a.file)[0]+"_analysis.json"
    with open(out,"w",encoding="utf-8") as f:json.dump(build_report(pcb,a.file,conn,a.full),f,indent=2,ensure_ascii=False)
    print("Đã lưu JSON:",out,"(%.1fs)"%(time.time()-t0))
if __name__=="__main__":main()
