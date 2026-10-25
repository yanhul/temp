#!/usr/bin/env python3
"""Evidence-preserving summary for altiumts records -- no record-order net mapping."""
import collections
import json
import re
import sys
from pathlib import Path

def main(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    groups=collections.defaultdict(list)
    for row in data:
        groups[str(row.get("recordKind") or "Unknown")].append(row.get("fields") or {})
    print(f"total_records={len(data)}")
    for kind in ("Board","Component","Net","Pad","Track","Via","Arc","Region","Rule","Class","Polygon","Fill","Text"):
        print(f"{kind.lower()}_records={len(groups[kind])}")
    for kind in ("Pad","Track","Via","Arc","Region","Polygon","Fill"):
        layer=collections.Counter(str(x.get("LAYER","<missing>")) for x in groups[kind])
        print(f"{kind.lower()}_layers={json.dumps(dict(layer),sort_keys=True)}")
    tracks=[x for x in groups["Track"] if x.get("NET") not in (None,"65535",65535,"-1",-1)]
    print(f"track_records_with_net_reference={len(tracks)}")
    print(f"track_widths={json.dumps(dict(collections.Counter(str(x.get('WIDTH','<missing>')) for x in tracks)),sort_keys=True)}")
    print(f"track_layers={json.dumps(dict(collections.Counter(str(x.get('LAYER','<missing>')) for x in tracks)),sort_keys=True)}")
    # Resolve only explicit parser-provided IDs. Never assume a Net record's array position is its ID.
    net_by_id={}
    for net in groups["Net"]:
        name=net.get("NAME")
        for key in ("INDEX","ID","NETID","NET_ID","UNIQUEID","UNIQUE_ID"):
            ident=net.get(key)
            if ident is not None and name is not None:
                net_by_id[str(ident)]=str(name)
    by_ref=collections.defaultdict(lambda: {"tracks":0,"vias":0,"layers":collections.Counter()})
    for track in tracks:
        ref=str(track.get("NET"))
        by_ref[ref]["tracks"]+=1
        by_ref[ref]["layers"][str(track.get("LAYER","<missing>"))]+=1
    for via in groups["Via"]:
        ref=via.get("NET")
        if ref not in (None,"65535",65535,"-1",-1):
            by_ref[str(ref)]["vias"]+=1
    print("top_net_references:")
    for ref,stats in sorted(by_ref.items(),key=lambda kv:(-kv[1]["tracks"],kv[0]))[:30]:
        name=net_by_id.get(ref)
        layers=dict(stats["layers"])
        print(f"  ref={ref} name={name if name is not None else '<unresolved-by-explicit-ID>'} tracks={stats['tracks']} vias={stats['vias']} layers={json.dumps(layers,sort_keys=True)}")
    special=re.compile(r"(USB|D[+-]|TX|RX|VBUS|GND|CLK|ADC|UART|ETH|MDI|RMII|MDC|MDIO)",re.I)
    print("special_named_nets:")
    for index,net in enumerate(groups["Net"]):
        name=str(net.get("NAME") or "")
        if special.search(name):
            print(f"  {name}")
    print("note=Net references are resolved only when the record explicitly supplies a matching identifier; record order is not treated as identity.")

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: summarize_altiumts_records.py pcb-records.json")
    main(sys.argv[1])
