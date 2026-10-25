#!/usr/bin/env python3
"""Standalone Altium PcbDoc binary inventory and conservative 2-layer routing analysis.

This is an independent parser branch. It does not replace altium-monkey and does
not claim DRC or complete connectivity when binary record decoding is uncertain.
"""
from __future__ import annotations
import argparse, hashlib, json, math, re, struct
from collections import Counter
from pathlib import Path

try:
    import olefile
except ImportError as exc:
    raise SystemExit("BLOCKED: install dependency with: python -m pip install olefile") from exc

STREAM_NAMES = ("Board6", "Components6", "Nets6", "Connections6", "Rules6",
                "Arcs6", "Pads6", "Vias6", "Tracks6", "Texts6", "Regions6",
                "Polygons6", "Texts", "Board")

def load_pcbdoc(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    with olefile.OleFileIO(str(path)) as ole:
        streams = {}
        for parts in ole.listdir(streams=True, storages=False):
            name = "/".join(parts)
            try:
                data = ole.openstream(parts).read()
            except Exception:
                continue
            streams[name] = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                             "_data": data}
    return {"path": str(path), "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "streams": streams}

def _raw(pcb, suffix):
    for name, row in pcb["streams"].items():
        if name.lower().endswith(suffix.lower()):
            return row["_data"]
    return b""

def _ascii_fields(data: bytes) -> dict:
    out = {}
    # Altium metadata streams often include NUL-delimited ASCII key=value records.
    text = data.replace(b"\x00", b" ").decode("latin-1", errors="ignore")
    for key in ("KIND","VERSION","DATE","TIME","ORIGINX","ORIGINY","ELECTRICALGRIDRANGE",
                "ELECTRICALGRIDENABLED","FILENAME","LAYER","BOARDWIDTH","BOARDHEIGHT"):
        m = re.search(r"(?i)(?:^|[ ;\r\n])" + re.escape(key) + r"\s*=\s*([^;\r\n\x00]{1,180})", text)
        if m:
            out[key.lower()] = m.group(1).strip()
    return out

def _record_inventory(data: bytes) -> dict:
    # Inventory candidate length-prefixed records without asserting record semantics.
    counts = Counter()
    pos, valid, malformed = 0, 0, 0
    while pos + 5 <= len(data):
        # Common Altium records begin with a one-byte type and 4-byte length.
        length_le = struct.unpack_from("<I", data, pos + 1)[0]
        if 0 < length_le <= len(data) - pos - 5:
            counts[str(data[pos])] += 1
            valid += 1
            pos += 5 + length_le
        else:
            malformed += 1
            pos += 1
    return {"candidate_records": valid, "candidate_type_counts": dict(counts),
            "resync_bytes": malformed, "decoder_status": "PARTIAL_HEURISTIC"}

def parse_track(data: bytes) -> dict:
    return _record_inventory(data)
def parse_via(data: bytes) -> dict:
    return _record_inventory(data)
def parse_pad(data: bytes) -> dict:
    return _record_inventory(data)
def parse_arc(data: bytes) -> dict:
    return _record_inventory(data)

def true_board_outline(pcb: dict) -> dict:
    # Outline reconstruction requires validated board-region/track geometry.
    return {"status": "UNKNOWN", "reason": "outline geometry is not reconstructed by heuristic record inventory"}

def analyze_connectivity(pcb: dict) -> dict:
    streams = pcb["streams"]
    required = ["Pads6", "Tracks6", "Vias6", "Connections6"]
    found = {key: next((v for k,v in streams.items() if k.lower().endswith(key.lower())), None) for key in required}
    missing = [k for k,v in found.items() if v is None]
    inventories = {}
    for key, fn in (("Pads6",parse_pad),("Tracks6",parse_track),("Vias6",parse_via),("Arcs6",parse_arc)):
        if key in required or any(k.lower().endswith(key.lower()) for k in streams):
            row = next((v for k,v in streams.items() if k.lower().endswith(key.lower())), None)
            if row is not None: inventories[key] = fn(row["_data"])
    return {"status": "UNKNOWN" if missing else "PARTIAL",
            "reason": "heuristic record inventory is not validated pad/net connectivity; airwire count is not inferred",
            "required_streams_missing": missing, "primitive_streams": inventories,
            "airwire_count": None, "connectivity_verified": False}

def build_report(pcb: dict, full: bool = False) -> dict:
    stream_public = {name: {k:v for k,v in row.items() if k != "_data"} for name,row in pcb["streams"].items()}
    meta_data = next((row["_data"] for name,row in pcb["streams"].items()
                      if name.lower().endswith("board6")), b"")
    report = {"schema": "altium-pcbdoc-standalone-report.v1",
              "status": "PARTIAL", "source": {"path": pcb["path"], "size_bytes": pcb["size_bytes"], "sha256": pcb["sha256"]},
              "metadata": _ascii_fields(meta_data), "stream_count": len(stream_public),
              "streams": stream_public, "board_outline": true_board_outline(pcb),
              "routing_analysis": analyze_connectivity(pcb),
              "limitations": ["record inventory uses heuristic length framing",
                              "no complete geometry, net mapping, clearance DRC, or verified airwire count"]}
    if not full:
        report["streams"] = {k:v for k,v in stream_public.items()
                             if any(k.lower().endswith(s.lower()) for s in STREAM_NAMES)}
    return report

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--no-analysis", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    try:
        pcb = load_pcbdoc(args.file)
        report = build_report(pcb, args.full)
        if args.no_analysis:
            report.pop("routing_analysis", None)
        payload = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
        return 0
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","error":type(exc).__name__,"message":str(exc)}), flush=True)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
