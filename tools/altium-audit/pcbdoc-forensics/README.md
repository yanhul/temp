# PcbDoc binary forensics (experimental)

This isolated toolset investigates the binary structure of an Altium `.PcbDoc`.
It is deliberately separate from the production audit runner and does not alter
source files or claim DRC/connectivity PASS.

## Install

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r tools/altium-audit/pcbdoc-forensics/requirements.txt
```

Use the same Python interpreter for installation and execution. Do not use a
system-package override unless you intentionally accept modifying system Python.

## Inventory OLE streams

```bash
python tools/altium-audit/pcbdoc-forensics/explore_format.py path/to/board.PcbDoc --json out/stream-inventory.json
```

The report records the exact source SHA-256, OLE signature, stream names/sizes,
and the first 32 bytes of each stream. It is an inventory, not a PCB decoder.

## Dump bytes from one stream

```bash
python tools/altium-audit/pcbdoc-forensics/dump_raw.py path/to/board.PcbDoc Tracks6 --offset 0 --length 512 --out out/Tracks6-prefix.bin
```

Stream names are matched case-insensitively but the complete stream path must
match exactly one stream. Dumps are bounded to 1 MiB per invocation.

## Record-decoder roadmap

1. Inventory compound-file streams and identify companion/header streams.
2. Reproduce the upstream parser's stream mapping and record framing.
3. Decode one object family at a time (track, arc, via, pad, component, net,
   region/polygon, layer and board outline), preserving raw bytes and offsets.
4. Add golden fixtures and round-trip/field-level tests before using decoded
   geometry in audit decisions.
5. Cross-check counts and coordinates against a trusted export or native
   Altium output. Every report must bind to the input SHA-256.

No unknown record may be silently skipped in a PASS-producing path. Until a
record family is decoded and validated, the corresponding audit domain remains
UNKNOWN/BLOCKED. This package does not replace native Altium DRC.
