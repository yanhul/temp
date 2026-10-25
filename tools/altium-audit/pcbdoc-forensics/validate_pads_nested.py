#!/usr/bin/env python3
"""Strict framing validator for Altium V6 Pads6 records.

The layout follows KiCad's published altium_parser.ksy: each pad contains six
length-prefixed subrecords. This validates structure and extracts only stable
structural facts; it does not claim full pad geometry or electrical validity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
MIN_PAD_SUB5 = 130
MAX_RECORDS = 2_000_000


def parse_pad_stream(data: bytes, header_count: int | None = None) -> dict:
    pos = 0
    pads = []
    errors = []
    while pos < len(data):
        start = pos
        if len(data) - pos < 5:
            errors.append({"offset": pos, "error": "truncated_record_header"})
            break
        record_type = data[pos]
        if record_type != 2:
            errors.append({"offset": pos, "error": "unexpected_record_type", "actual": record_type, "expected": 2})
            break
        pos += 1
        lengths = []
        bounds_ok = True
        for index in range(1, 7):
            if len(data) - pos < 4:
                errors.append({"offset": pos, "error": "truncated_subrecord_length", "subrecord": index})
                bounds_ok = False
                break
            length = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
            if length > len(data) - pos:
                errors.append({"offset": pos - 4, "error": "subrecord_out_of_bounds", "subrecord": index, "length": length, "available": len(data) - pos})
                bounds_ok = False
                break
            lengths.append(length)
            pos += length
        if not bounds_ok:
            break
        if lengths[4] < MIN_PAD_SUB5:
            errors.append({"offset": start, "error": "pad_sub5_too_short", "length": lengths[4], "minimum": MIN_PAD_SUB5})
            break
        pads.append({
            "offset": start,
            "record_type": record_type,
            "subrecord_lengths": lengths,
            "designator_bytes": lengths[0],
            "has_layer_stack_subrecord": lengths[5] > 0,
        })
        if len(pads) > MAX_RECORDS:
            errors.append({"offset": start, "error": "record_limit_exceeded"})
            break

    matches = None if header_count is None else header_count == len(pads)
    status = "PASS" if not errors and pos == len(data) and matches is not False else "BLOCKED"
    return {
        "stream": "Pads6",
        "stream_size_bytes": len(data),
        "pads_framed": len(pads),
        "bytes_consumed": pos,
        "trailing_bytes": len(data) - pos,
        "header_count": header_count,
        "header_count_matches": matches,
        "status": status,
        "records": pads,
        "errors": errors,
        "scope": "Nested record framing only; pad dimensions, stack semantics, connectivity and DRC are not validated.",
        "format_reference": "KiCad kicad-source-mirror pcbnew/pcb_io/altium/altium_parser.ksy (pad, pad_sub1, pad_sub5, pad_sub6)"
    }


def read_header_count(ole) -> int | None:
    if not ole.exists(["Pads6", "Header"]):
        return None
    with ole.openstream(["Pads6", "Header"]) as stream:
        raw = stream.read()
    return int.from_bytes(raw, "little") if len(raw) == 4 else None


def inspect(pcbdoc: Path) -> dict:
    with pcbdoc.open("rb") as f:
        if f.read(8) != OLE_MAGIC:
            raise ValueError("input does not have OLE Compound File signature")
    import olefile
    if not olefile.isOleFile(str(pcbdoc)):
        raise ValueError("olefile rejected input as OLE compound file")
    digest = hashlib.sha256(pcbdoc.read_bytes()).hexdigest()
    with olefile.OleFileIO(str(pcbdoc)) as ole:
        if not ole.exists(["Pads6", "Data"]):
            return {"source": str(pcbdoc), "source_sha256": digest, "status": "BLOCKED", "fatal_error": "Pads6/Data stream missing"}
        with ole.openstream(["Pads6", "Data"]) as stream:
            data = stream.read()
        report = parse_pad_stream(data, read_header_count(ole))
    report.update({"source": str(pcbdoc), "source_size_bytes": pcbdoc.stat().st_size, "source_sha256": digest})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcbdoc", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = inspect(args.pcbdoc)
    except Exception as exc:
        report = {"source": str(args.pcbdoc), "status": "BLOCKED", "fatal_error": f"{type(exc).__name__}: {exc}"}
    rendered = json.dumps(report, indent=2)
    print(rendered)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
