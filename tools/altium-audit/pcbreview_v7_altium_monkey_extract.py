#!/usr/bin/env python3
"""Export the public decoded Altium PcbDoc object model from altium-monkey.

Read-only: never saves or mutates the source board. Serializes dataclass fields,
instance attributes and slots recursively, retaining unknown/public fields instead
of maintaining a hand-written reduced PCB schema.
"""
from __future__ import annotations
import argparse
import dataclasses
import enum
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from altium_monkey import AltiumPcbDoc

COLLECTION_CANDIDATES = (
    "components", "nets", "tracks", "arcs", "pads", "vias", "fills",
    "texts", "regions", "polygons", "polygon_pours", "design_rules", "rules",
    "dimensions", "from_tos", "net_classes", "differential_pairs",
    "board_regions", "classes", "models", "fonts", "embedded_models",
    "component_bodies", "mechanical_layer_kinds", "layer_stack", "stackup",
    "board_outline", "board", "layers",
)


def safe_get(obj: Any, name: str):
    try:
        return getattr(obj, name)
    except Exception as exc:
        return {"__read_error__": f"{type(exc).__name__}: {exc}"}


def object_fields(obj: Any) -> dict[str, Any]:
    """Collect fields exposed by Python's data model, including slots."""
    out: dict[str, Any] = {}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        try:
            for field in dataclasses.fields(obj):
                if not field.name.startswith("_"):
                    out[field.name] = safe_get(obj, field.name)
        except Exception:
            pass
    try:
        for key, value in vars(obj).items():
            if not key.startswith("_"):
                out.setdefault(key, value)
    except (TypeError, AttributeError):
        pass
    for cls in type(obj).__mro__:
        slots = getattr(cls, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for key in slots:
            if key.startswith("_") or key in out:
                continue
            try:
                out[key] = getattr(obj, key)
            except Exception as exc:
                out[key] = {"__read_error__": f"{type(exc).__name__}: {exc}"}
    return out


def serialize(value: Any, *, depth: int = 0, seen: set[int] | None = None,
              include_binary: bool = False) -> Any:
    if seen is None:
        seen = set()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, enum.Enum):
        return {"name": value.name, "value": serialize(value.value, depth=depth+1, seen=seen, include_binary=include_binary)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        result = {"__binary__": True, "length_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if include_binary:
            import base64
            result["base64"] = base64.b64encode(raw).decode("ascii")
        return result
    if depth > 32:
        return {"__truncated__": "maximum object depth"}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [serialize(v, depth=depth+1, seen=seen, include_binary=include_binary) for v in value]
    if isinstance(value, dict):
        return {str(k): serialize(v, depth=depth+1, seen=seen, include_binary=include_binary)
                for k, v in value.items()}
    if callable(value):
        return {"__callable__": getattr(value, "__qualname__", type(value).__name__)}
    oid = id(value)
    if oid in seen:
        return {"__cycle_ref__": f"{type(value).__module__}.{type(value).__qualname__}"}
    seen.add(oid)
    fields = object_fields(value)
    if not fields:
        return {"__object_type__": f"{type(value).__module__}.{type(value).__qualname__}",
                "__repr__": repr(value)[:500]}
    result = {"__object_type__": f"{type(value).__module__}.{type(value).__qualname__}"}
    for key, val in fields.items():
        if callable(val):
            continue
        result[key] = serialize(val, depth=depth+1, seen=seen, include_binary=include_binary)
    seen.remove(oid)
    return result


def inventory_collection(value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        types = Counter(f"{type(x).__module__}.{type(x).__qualname__}" for x in items)
        return {"count": len(items), "item_types": dict(sorted(types.items()))}
    if isinstance(value, dict):
        return {"count": len(value), "mapping": True}
    return {"count": None, "value_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def extract(path: Path, include_binary: bool = False) -> dict[str, Any]:
    source_bytes = path.read_bytes()
    board = AltiumPcbDoc.from_file(str(path))
    root_fields = object_fields(board)

    collections: dict[str, Any] = {}
    for name in COLLECTION_CANDIDATES:
        if name not in root_fields:
            value = safe_get(board, name)
            if isinstance(value, dict) and "__read_error__" in value:
                continue
            # Keep only collection-like or model-like properties, not methods.
            if not isinstance(value, (list, tuple, set, frozenset, dict)) and not dataclasses.is_dataclass(value):
                continue
        else:
            value = root_fields[name]
        if callable(value):
            continue
        collections[name] = {
            "inventory": inventory_collection(value),
            "data": serialize(value, include_binary=include_binary),
        }

    # Capture any other public non-callable root fields so library additions are not
    # silently dropped; known collections above are represented once in collections.
    root_metadata = {}
    for name, value in root_fields.items():
        if name in COLLECTION_CANDIDATES or callable(value):
            continue
        root_metadata[name] = serialize(value, include_binary=include_binary)

    # Also record the public property surface, including access failures, for future
    # library versions whose fields are not dataclass/slots/instance attributes.
    public_surface = {}
    for name in dir(board):
        if name.startswith("_") or name in COLLECTION_CANDIDATES or name in root_fields:
            continue
        try:
            value = getattr(board, name)
        except Exception as exc:
            public_surface[name] = {"__read_error__": f"{type(exc).__name__}: {exc}"}
            continue
        if callable(value):
            continue
        if isinstance(value, (str, int, float, bool, type(None), list, tuple, set, frozenset, dict, enum.Enum, bytes, bytearray)) or dataclasses.is_dataclass(value):
            public_surface[name] = serialize(value, include_binary=include_binary)

    return {
        "schema": "pcbreview.altium_monkey_full_extract/1.0",
        "status": "PARSED_UNVERIFIED",
        "source": {
            "filename": path.name,
            "size_bytes": len(source_bytes),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "library": "altium-monkey",
            "read_only": True,
        },
        "library_model_type": f"{type(board).__module__}.{type(board).__qualname__}",
        "root_metadata": root_metadata,
        "collections": collections,
        "additional_public_properties": public_surface,
        "limitations": [
            "This exports the public object model decoded by the installed altium-monkey version; it does not imply every undocumented Altium binary record is supported.",
            "A successful parse is not an Altium DRC, electrical-connectivity, manufacturing, or release certification.",
            "Binary payload fields are represented by byte length and SHA-256 by default; pass --include-binary to embed bytes as base64 in JSON.",
            "Source file is read only and never saved by this extractor.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--include-binary", action="store_true",
                    help="embed binary fields as base64 (can make JSON very large)")
    args = ap.parse_args()
    report = extract(args.file, args.include_binary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {name: info["inventory"] for name, info in report["collections"].items()}
    print("ALTIUM_MONKEY_PARSE=PASS")
    print("STATUS=" + report["status"])
    print("SOURCE_SHA256=" + report["source"]["sha256"])
    print("COLLECTIONS=" + json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print("OUTPUT=" + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
