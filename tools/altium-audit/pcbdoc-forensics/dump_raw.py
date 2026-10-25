#!/usr/bin/env python3
"""Dump a bounded raw byte window from a named stream in an Altium PcbDoc.

Never writes over the source. Output includes source SHA-256 and stream path.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcbdoc", type=Path)
    ap.add_argument("stream", help="OLE stream path, e.g. Tracks6 or Board6")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--length", type=int, default=256)
    ap.add_argument("--out", type=Path, required=True, help="Raw bytes output path")
    args = ap.parse_args()

    if args.offset < 0 or args.length < 1 or args.length > 1_048_576:
        ap.error("offset must be >= 0 and length must be in 1..1048576")
    with args.pcbdoc.open("rb") as f:
        if f.read(8) != OLE_MAGIC:
            raise SystemExit("BLOCKED: input is not an OLE Compound File")
    try:
        import olefile
    except ImportError:
        raise SystemExit("BLOCKED: install dependency with python -m pip install olefile")

    if not olefile.isOleFile(str(args.pcbdoc)):
        raise SystemExit("BLOCKED: olefile rejected input")
    with olefile.OleFileIO(str(args.pcbdoc)) as ole:
        candidates = [p for p in ole.listdir(streams=True, storages=False)
                      if "/".join(p).casefold() == args.stream.casefold()]
        if len(candidates) != 1:
            available = [" / ".join(p) for p in ole.listdir(streams=True, storages=False)]
            raise SystemExit(f"BLOCKED: stream must match exactly one path; available={available}")
        stream_path = candidates[0]
        size = ole.get_size(stream_path)
        if args.offset > size:
            raise SystemExit(f"BLOCKED: offset {args.offset} exceeds stream size {size}")
        with ole.openstream(stream_path) as stream:
            stream.seek(args.offset)
            data = stream.read(min(args.length, size - args.offset))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"source={args.pcbdoc}")
    print(f"source_sha256={sha256_file(args.pcbdoc)}")
    print(f"stream={'/'.join(stream_path)}")
    print(f"stream_size={size}")
    print(f"offset={args.offset}")
    print(f"bytes_written={len(data)}")
    print(f"output={args.out}")
    print("hex:")
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        textpart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{args.offset+i:08x}  {hexpart:<47}  {textpart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
