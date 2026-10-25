#!/usr/bin/env python3
"""Validate byte framing for supported single-subrecord Altium V6 primitive streams.

Pads6 is deliberately reported as UNSUPPORTED because its records contain nested/
secondary subrecords; treating it as a flat stream caused a false framing failure.
This tool does not decode geometry or claim connectivity/DRC validity.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
EXPECTED_TYPES = {"Arcs6": 1, "Vias6": 3, "Tracks6": 4}
UNSUPPORTED_STREAMS = {
    "Pads6": "Pad records contain additional subrecords and require a dedicated nested-record parser."
}
MAX_RECORDS = 2_000_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_stream(data: bytes, stream_name: str, header_count: int | None = None) -> dict:
    expected = EXPECTED_TYPES[stream_name]
    pos = 0
    records = []
    errors = []
    while pos < len(data):
        start = pos
        if len(data) - pos < 5:
            errors.append({"offset": pos, "error": "truncated_record_header", "remaining": len(data)-pos})
            break
        record_type = data[pos]
        length = int.from_bytes(data[pos + 1:pos + 5], "little", signed=False)
        payload_start = pos + 5
        end = payload_start + length
        if record_type != expected:
            errors.append({"offset": pos, "error": "unexpected_record_type", "actual": record_type, "expected": expected})
            break
        if length == 0:
            errors.append({"offset": pos, "error": "zero_length_subrecord"})
            break
        if end > len(data):
            errors.append({"offset": pos, "error": "subrecord_out_of_bounds", "length": length, "available": len(data)-payload_start})
            break
        records.append({"offset": start, "record_type": record_type, "payload_length": length})
        if len(records) > MAX_RECORDS:
            errors.append({"offset": pos, "error": "record_limit_exceeded"})
            break
        pos = end
    matches = None if header_count is None else header_count == len(records)
    status = "PASS" if not errors and pos == len(data) and matches is not False else "BLOCKED"
    return {
        "stream": stream_name,
        "expected_record_type": expected,
        "stream_size_bytes": len(data),
        "records_framed": len(records),
        "bytes_consumed": pos,
        "trailing_bytes": len(data) - pos,
        "header_count": header_count,
        "header_count_matches": matches,
        "status": status,
        "errors": errors,
        "note": "Framing only; not geometry, connectivity, layer or DRC validation."
    }


def inspect(pcbdoc: Path) -> dict:
    with pcbdoc.open("rb") as f:
        if f.read(8) != OLE_MAGIC:
            raise ValueError("input does not have OLE Compound File signature")
    import olefile
    if not olefile.isOleFile(str(pcbdoc)):
        raise ValueError("olefile rejected input as OLE compound file")
    sha = sha256_file(pcbdoc)
    results = []
    with olefile.OleFileIO(str(pcbdoc)) as ole:
        for name, reason in UNSUPPORTED_STREAMS.items():
            results.append({
                "stream": name,
                "status": "UNSUPPORTED",
                "header_count": _read_header_count(ole, name),
                "reason": reason,
                "note": "Excluded from PASS accounting; this family remains unaudited."
            })
        for name in EXPECTED_TYPES:
            data_path = [name, "Data"]
            if not ole.exists(data_path):
                results.append({"stream": name, "status": "BLOCKED", "errors": [{"error": "missing_data_stream"}]})
                continue
            with ole.openstream(data_path) as stream:
                data = stream.read()
            results.append(analyze_stream(data, name, _read_header_count(ole, name)))
    supported = [r for r in results if r["stream"] in EXPECTED_TYPES]
    supported_pass = all(r.get("status") == "PASS" for r in supported)
    all_supported_present = len(supported) == len(EXPECTED_TYPES)
    status = "PASS" if supported_pass and all_supported_present and not UNSUPPORTED_STREAMS else "PARTIAL"
    if not supported_pass:
        status = "BLOCKED"
    return {
        "source": str(pcbdoc),
        "source_size_bytes": pcbdoc.stat().st_size,
        "source_sha256": sha,
        "status": status,
        "families": results,
        "unsupported_families": list(UNSUPPORTED_STREAMS),
        "scope": "Arcs6, Vias6 and Tracks6 framing only; Pads6 nested records and all geometry/electrical semantics remain unverified"
    }


def _read_header_count(ole, name: str) -> int | None:
    path = [name, "Header"]
    if not ole.exists(path):
        return None
    with ole.openstream(path) as stream:
        header = stream.read()
    return int.from_bytes(header, "little") if len(header) == 4 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcbdoc", type=Path)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    try:
        report = inspect(args.pcbdoc)
    except Exception as exc:
        report = {"source": str(args.pcbdoc), "status": "BLOCKED", "fatal_error": f"{type(exc).__name__}: {exc}"}
    rendered = json.dumps(report, indent=2)
    print(rendered)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] in {"PASS", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
