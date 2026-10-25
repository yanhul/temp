#!/usr/bin/env python3
"""Inspect an Altium PcbDoc OLE compound file without modifying it.

Reports source SHA-256, OLE streams, stream sizes, and small leading signatures.
This is format reconnaissance only; it does not claim to decode PCB records.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect(path: Path) -> dict:
    with path.open("rb") as f:
        head = f.read(8)
    result = {
        "source": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "header_hex": head.hex(),
        "ole_signature": head == OLE_MAGIC,
        "status": "BLOCKED",
        "streams": [],
        "notes": [],
    }
    if head != OLE_MAGIC:
        result["notes"].append("Input does not begin with the OLE Compound File signature.")
        return result
    try:
        import olefile
    except ImportError:
        result["notes"].append("Missing dependency: install with python -m pip install olefile.")
        return result

    if not olefile.isOleFile(str(path)):
        result["notes"].append("olefile rejected the input as an OLE compound file.")
        return result

    with olefile.OleFileIO(str(path)) as ole:
        for parts in ole.listdir(streams=True, storages=False):
            entry = {"path": "/".join(parts), "size_bytes": ole.get_size(parts)}
            try:
                with ole.openstream(parts) as stream:
                    entry["prefix_hex"] = stream.read(32).hex()
            except Exception as exc:
                entry["read_error"] = f"{type(exc).__name__}: {exc}"
            result["streams"].append(entry)
    result["streams"].sort(key=lambda x: x["path"].lower())
    result["status"] = "INSPECTED"
    result["notes"].append("Stream inventory only; record layouts and semantics are not yet validated.")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcbdoc", type=Path)
    ap.add_argument("--json", dest="json_path", type=Path)
    args = ap.parse_args()
    report = inspect(args.pcbdoc)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "INSPECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
