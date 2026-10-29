"""Source-backed audit of local Altium schematic libraries (.SchLib)."""
from __future__ import annotations
import hashlib, re
from pathlib import Path
from typing import Any

def _norm(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(v or "").upper())

def _field(o: Any, *keys: str) -> Any:
    if isinstance(o, dict):
        for k in keys:
            if o.get(k) is not None: return o[k]
    for k in keys:
        try:
            v = getattr(o, k)
            if v is not None: return v
        except Exception: pass
    return None

def _pin_map(symbol: Any) -> dict[str, dict[str, str]]:
    try: pins = list(_field(symbol, "pins") or [])
    except Exception: pins = []
    out = {}
    for pin in pins:
        number = _field(pin, "designator", "pin_designator", "number", "pin_number")
        if number is None: continue
        name = _field(pin, "name", "pin_name", "description")
        electrical = _field(pin, "electrical_type", "electrical", "pin_type", "electrical_kind")
        out[str(number).strip()] = {"name": str(name or "").strip(),
                                    "electrical_type": str(electrical or "").strip()}
    return out

def audit_local_schlibs(root: str | Path, components: list[dict[str, Any]], add) -> dict[str, Any]:
    """Exact-name SchLib pin comparison; no fuzzy or footprint-derived identity."""
    root = Path(root)
    files = sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.casefold()==".schlib"),
                   key=lambda p: str(p).casefold())
    try:
        from altium_monkey import AltiumSchLib
    except Exception as exc:
        add("G2-SCHLIB-SOURCE-PARSER","BLOCKER","schematic","BLOCKED",
            f"Cannot import AltiumSchLib: {type(exc).__name__}: {exc}","FACT",None)
        return {"files_found":len(files),"files_parsed":0,"symbols":0}
    index, parsed, errors = {}, 0, []
    for path in files:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lib = AltiumSchLib(path); parsed += 1
            for sym in lib.symbols:
                names = {_norm(_field(sym,k)) for k in ("name","original_name","library_reference","lib_reference")}
                entry = {"name":str(_field(sym,"name") or ""),
                         "path":str(path.relative_to(root)), "sha256":digest, "pins":_pin_map(sym)}
                for name in names:
                    if name: index.setdefault(name,[]).append(entry)
        except Exception as exc:
            errors.append(f"{path.relative_to(root)}: {type(exc).__name__}: {exc}")
    if not files:
        add("G2-SCHLIB-SOURCE-INVENTORY","BLOCKER","schematic","UNKNOWN",
            "No .SchLib source exists under the audited input root. This says nothing about libraries outside the supplied project/archive; source-backed pin resolution is unavailable for this run.","FACT",None)
    if errors:
        add("G2-SCHLIB-SOURCE-PARSE","BLOCKER","schematic","UNKNOWN",
            f"Could not parse {len(errors)} local SchLib file(s): {'; '.join(errors[:8])}","FACT",None)
    matched = 0
    for comp in components or []:
        ref = str(comp.get("reference") or comp.get("designator") or "").strip()
        identity = comp.get("library_id") or comp.get("library_reference") or comp.get("library") or ""
        if not ref or not identity: continue
        candidates = index.get(_norm(identity), [])
        if len(candidates) != 1:
            if candidates or (files and parsed):
                why = f"ambiguous ({len(candidates)} exact matches)" if candidates else "no exact symbol match"
                add("G2-SCHLIB-SYMBOL-"+("AMBIGUOUS-" if candidates else "MISSING-")+ref,
                    "BLOCKER","schematic","UNKNOWN",
                    f"Local SchLib identity {identity!r} is {why}; fuzzy matching is disabled.","FACT",ref)
            continue
        src = candidates[0]; observed = comp.get("pins") or []
        if isinstance(observed,dict):
            observed=[{"pin":k,**(v if isinstance(v,dict) else {"pin_name":v})} for k,v in observed.items()]
        compared, conflicts = [], []
        for pin in observed:
            n = pin.get("pin") or pin.get("pin_number") or pin.get("number")
            if n is None or str(n) not in src["pins"]: continue
            expected = src["pins"][str(n)].get("name","")
            actual = str(pin.get("pin_name") or pin.get("name") or "").strip()
            if not expected or not actual: continue
            row={"pin":str(n),"source_name":expected,"compiled_name":actual}; compared.append(row)
            if _norm(expected) != _norm(actual): conflicts.append(row)
        matched += 1; provenance=f"{src['path']} sha256:{src['sha256']}"
        if conflicts:
            add("G2-SCHLIB-PINMAP-"+ref,"BLOCKER","schematic","FAIL",
                f"Compiled pin names conflict with exact local symbol {src['name']!r} ({provenance}): {conflicts}","VERIFIED",ref)
        elif compared:
            add("G2-SCHLIB-PINMAP-"+ref,"INFO","schematic","VERIFIED",
                f"{len(compared)} connected pin name(s) match exact local symbol {src['name']!r}; source={provenance}. This verifies the symbol pin map, not physical manufacturer-part identity.","VERIFIED",ref)
        else:
            add("G2-SCHLIB-PINMAP-"+ref,"BLOCKER","schematic","UNKNOWN",
                f"Exact local symbol {src['name']!r} exists ({provenance}), but no comparable connected pin names were available.","FACT",ref)
    if files and parsed and not errors:
        add("G2-SCHLIB-SOURCE-INVENTORY","INFO","schematic","VERIFIED",
            f"Parsed {parsed} local .SchLib file(s), indexed {len(index)} exact symbol key(s), matched {matched} compiled component(s); no fuzzy matching used.","VERIFIED",None)
    return {"files_found":len(files),"files_parsed":parsed,"symbols":len(index),"matched_components":matched,"errors":errors}
