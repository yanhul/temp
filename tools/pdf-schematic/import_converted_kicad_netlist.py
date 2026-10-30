#!/usr/bin/env python3
"""Import a KiCad XML netlist without promoting converter output to native truth.

The imported component/pin/net membership is exact for the supplied KiCad
netlist. It remains CONVERTED_UNVERIFIED until independently compared with the
original Altium SchDoc. Explicit junction objects are retained as evidence,
not treated as sufficient proof of electrical connectivity by themselves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sexpr_tokens(source: str):
    """Small S-expression tokenizer sufficient for KiCad structural evidence."""
    token_re = re.compile(r'\s+|;[^\n]*|"(?:\\.|[^"\\])*"|[()]|[^\s()]+')
    for match in token_re.finditer(source):
        token = match.group(0)
        if token.isspace() or token.startswith(";"):
            continue
        yield token


def _parse_sexpr(source: str):
    tokens = iter(_sexpr_tokens(source))
    stack = []
    root = None
    for token in tokens:
        if token == "(":
            node = []
            if stack:
                stack[-1].append(node)
            else:
                if root is not None:
                    raise ValueError("multiple top-level S-expressions")
                root = node
            stack.append(node)
        elif token == ")":
            if not stack:
                raise ValueError("unbalanced closing parenthesis")
            stack.pop()
        else:
            if not stack:
                raise ValueError("atom outside S-expression")
            if token.startswith('"'):
                # JSON string decoding is compatible with KiCad's escaped quotes.
                import json as _json
                stack[-1].append(_json.loads(token))
            else:
                stack[-1].append(token)
    if stack or root is None:
        raise ValueError("unbalanced or empty KiCad S-expression")
    return root


def extract_explicit_junctions(kicad_sch: Path):
    tree = _parse_sexpr(kicad_sch.read_text(encoding="utf-8"))
    result = []

    def walk(node):
        if not isinstance(node, list):
            return
        if node and node[0] == "junction":
            at = next((child for child in node[1:] if isinstance(child, list)
                       and child and child[0] == "at"), None)
            if at is None or len(at) < 3:
                raise ValueError("KiCad junction lacks a valid (at x y) coordinate")
            x, y = float(at[1]), float(at[2])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("KiCad junction has non-finite coordinates")
            result.append({"x": x, "y": y,
                           "authority": "EXPLICIT_CONVERTED_KICAD_JUNCTION_OBJECT"})
        for child in node:
            walk(child)

    walk(tree)
    return sorted(result, key=lambda item: (item["x"], item["y"]))


def build(netlist_xml: str, provenance: dict, junctions=None):
    root = ET.fromstring(netlist_xml)
    if root.tag != "export":
        raise ValueError("netlist root must be <export>")

    source_hashes = ("source_schdoc_sha256", "converted_kicad_sch_sha256",
                     "netlist_sha256")
    for key in source_hashes:
        value = provenance.get(key, "")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"missing/invalid provenance hash: {key}")

    components_parent = root.find("components")
    nets_parent = root.find("nets")
    if components_parent is None or nets_parent is None:
        raise ValueError("netlist must contain <components> and <nets>")

    symbols = []
    refs = set()
    for comp in components_parent.findall("comp"):
        ref = comp.get("ref", "").strip()
        if not ref or ref in refs:
            raise ValueError(f"missing or duplicate component reference: {ref!r}")
        refs.add(ref)
        libsource = comp.find("libsource")
        if libsource is None or not libsource.get("lib") or not libsource.get("part"):
            raise ValueError(f"component {ref} has no complete libsource identity")
        symbols.append({
            "reference": ref,
            "value": comp.findtext("value", default=""),
            "footprint": comp.findtext("footprint", default=""),
            "lib_id": f"{libsource.get('lib')}:{libsource.get('part')}",
            "authority": "CONVERTED_KICAD_NETLIST_COMPONENT",
        })
    if not symbols:
        raise ValueError("netlist contains no components")

    nets = []
    pins = []
    seen_pin_assignments = set()
    seen_net_codes = set()
    seen_net_names = set()
    for net in nets_parent.findall("net"):
        code, name = net.get("code", "").strip(), net.get("name", "").strip()
        if not code or not name or code in seen_net_codes or name in seen_net_names:
            raise ValueError(f"missing or duplicate net code/name: {code!r}/{name!r}")
        seen_net_codes.add(code)
        seen_net_names.add(name)
        members = []
        for node in net.findall("node"):
            ref, pin_number = node.get("ref", "").strip(), node.get("pin", "").strip()
            if ref not in refs or not pin_number:
                raise ValueError(f"net {name} references unknown component or empty pin")
            key = (ref, pin_number)
            if key in seen_pin_assignments:
                raise ValueError(f"pin {ref}.{pin_number} assigned to more than one net")
            seen_pin_assignments.add(key)
            pin = {
                "reference": ref, "number": pin_number,
                "function": node.get("pinfunction"),
                "electrical_type": node.get("pintype"),
                "net_code": code, "net_name": name,
                "authority": "CONVERTED_KICAD_NETLIST_PIN_MEMBERSHIP",
            }
            pins.append(pin)
            members.append({"reference": ref, "pin": pin_number})
        if not members:
            raise ValueError(f"net {name} has no pin members")
        nets.append({
            "code": code, "name": name,
            "members": sorted(members, key=lambda item: (item["reference"], item["pin"])),
            "authority": "CONVERTED_KICAD_NETLIST_NET_MEMBERSHIP",
        })

    return {
        "schema": "converted-kicad-netlist-ir/v1",
        "status": "CONVERTED_UNVERIFIED_NATIVE_ALTIUM_EQUIVALENCE",
        "provenance": dict(provenance),
        "symbols": sorted(symbols, key=lambda item: item["reference"]),
        "pins": sorted(pins, key=lambda item: (item["reference"], item["number"])),
        "nets": sorted(nets, key=lambda item: (item["code"], item["name"])),
        "junction_evidence": list(junctions or []),
        "counts": {
            "symbol_count": len(symbols),
            "resolved_pin_membership_count": len(pins),
            "net_count": len(nets),
            "explicit_junction_object_count": len(junctions or []),
        },
        "unknown_reasons": [
            "CONVERTER_OUTPUT_NOT_INDEPENDENTLY_EQUIVALENT_TO_NATIVE_ALTIUM_SCHDOC",
            "KICAD_NETLIST_PIN_MEMBERSHIP_IS_NOT_A_NATIVE_ALTIUM_GOLDEN_NETLIST",
            "EXPLICIT_JUNCTION_OBJECTS_DO_NOT_ALONE_PROVE_NET_MEMBERSHIP",
            "UNCONNECTED_AND_NO_CONNECT_PINS_REQUIRE_SEPARATE_SCHEMATIC_OBJECT_AUDIT",
        ],
        "policy": {
            "pin_numbers_inferred": False,
            "net_membership_inferred_from_geometry": False,
            "junctions_inferred_from_visual_dots": False,
            "native_altium_equivalence_claimed": False,
            "unknown_is_fail_closed": True,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--netlist", type=Path, required=True)
    ap.add_argument("--source-schdoc", type=Path, required=True)
    ap.add_argument("--converted-kicad-sch", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    for path in (args.netlist, args.source_schdoc, args.converted_kicad_sch):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"BLOCKED: missing/empty input: {path}")
    provenance = {
        "source_schdoc": args.source_schdoc.name,
        "source_schdoc_sha256": sha256(args.source_schdoc),
        "converted_kicad_sch": args.converted_kicad_sch.name,
        "converted_kicad_sch_sha256": sha256(args.converted_kicad_sch),
        "netlist": args.netlist.name,
        "netlist_sha256": sha256(args.netlist),
    }
    junctions = extract_explicit_junctions(args.converted_kicad_sch)
    result = build(args.netlist.read_text(encoding="utf-8"), provenance, junctions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "counts": result["counts"],
                      "unknown_reasons": result["unknown_reasons"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
