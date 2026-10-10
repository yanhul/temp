#!/usr/bin/env python3
"""Evidence-first part identity resolution.

This module never chooses a replacement part. It only classifies whether the
declared part is consistent with observed compiled symbol evidence.
"""
from __future__ import annotations

import re
from typing import Any


def norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


# Manufacturer/datasheet-backed pin fingerprints. These are fingerprints,
# not repair instructions. Unknown/missing pins remain UNKNOWN.
AUTHORITATIVE_PIN_PROFILES = {
    "HCPL0600": {
        "source": "Broadcom HCPL-0600 datasheet/product page",
        "pins": {"1": "NC", "2": "ANODE", "3": "CATHODE", "4": "NC",
                 "5": "GND", "6": "VO", "7": "VE", "8": "VCC"},
    },
    "HCPL3120": {
        "source": "Broadcom HCPL-3120 datasheet/product page",
        "pins": {"1": "NC", "2": "ANODE", "3": "CATHODE", "4": "NC",
                 "5": "VEE", "6": "VO", "7": "VO", "8": "VCC"},
    },
    "BCX56": {
        "source": "Nexperia BCX56 series datasheet",
        "pins": {"1": "E", "2": "C", "3": "B"},
    },
    "PC817": {
        "source": "SHARP PC817 series datasheet",
        "pins": {"1": "ANODE", "2": "CATHODE", "3": "EMITTER", "4": "COLLECTOR"},
    },
    "TL2904": {
        "source": "TL2904/LM2904 8-pin dual operational-amplifier reference",
        "pins": {"1": "OUT", "2": "-", "3": "+", "4": "V-", "5": "+", "6": "-", "7": "OUT", "8": "V+"},
    },
}


# Datasheet-backed electrical identity attributes. Pin fingerprints alone cannot
# distinguish TVS variants whose package/pins match but voltage ratings differ.
AUTHORITATIVE_PART_SPECS = {
    "SMAJ15CA": {
        "source": "Diodes Incorporated SMAJ15CA product specification",
        "family": "SMAJ",
        "reverse_standoff_v": 15.0,
        "directionality": "BIDIRECTIONAL",
        "package": "SMA",
    },
    "SMAJ30CA": {
        "source": "Diodes Incorporated SMAJ30CA product specification",
        "family": "SMAJ",
        "reverse_standoff_v": 30.0,
        "directionality": "BIDIRECTIONAL",
        "package": "SMA",
    },
}


def profile_key(identity: Any) -> str:
    """Map compiled library/order-code strings onto authoritative families."""
    n = norm(identity)
    if "HCPL3120" in n:
        return "HCPL3120"
    if "HCPL0600" in n:
        return "HCPL0600"
    if "BCX56" in n:
        return "BCX56"
    if "PC817" in n:
        return "PC817"
    if "TL2904" in n:
        return "TL2904"
    return n


def pin_key(identity: Any) -> str:
    n = norm(identity)
    return "VO" if n == "V0" else n


def resolve_declared_vs_compiled(
    declared_value: str | None,
    compiled_library: str | None,
    observed_pins: dict[str, dict[str, Any]] | None,
    declared_profile_override: str | None = None,
) -> dict[str, Any]:
    """Return CONSISTENT, CONTRADICTION, or UNKNOWN.

    A library-name mismatch alone is evidence of contradiction only when the
    observed pin fingerprint also agrees with the compiled candidate. This
    avoids treating arbitrary symbol/library naming as proof of electrical
    identity.
    """
    declared = profile_key(declared_value)
    compiled = profile_key(compiled_library)
    effective_declared = profile_key(declared_profile_override) if declared_profile_override else declared
    observed_pins = observed_pins or {}

    if not declared or not compiled:
        return {
            "state": "UNKNOWN",
            "reason": "Declared value or compiled library identity is missing.",
            "evidence": [],
        }

    declared_spec = AUTHORITATIVE_PART_SPECS.get(effective_declared)
    compiled_spec = AUTHORITATIVE_PART_SPECS.get(compiled)
    if declared_spec and compiled_spec:
        conflicts = {
            key: {"declared": declared_spec.get(key), "compiled": compiled_spec.get(key)}
            for key in ("family", "reverse_standoff_v", "directionality", "package")
            if declared_spec.get(key) != compiled_spec.get(key)
        }
        if conflicts:
            return {
                "state": "CONTRADICTION",
                "reason": "Declared and compiled part identities conflict on authoritative electrical/package specifications.",
                "evidence": [{"attribute": key, **values} for key, values in conflicts.items()],
                "declared_profile_source": declared_spec["source"],
                "compiled_profile_source": compiled_spec["source"],
            }

    declared_profile = AUTHORITATIVE_PIN_PROFILES.get(effective_declared)
    compiled_profile = AUTHORITATIVE_PIN_PROFILES.get(compiled)

    if not declared_profile or not compiled_profile:
        if declared == compiled:
            return {"state": "CONSISTENT", "reason": "Declared and compiled identities match.", "evidence": []}
        return {
            "state": "UNKNOWN",
            "reason": "Different identities are present, but one or both lack an authoritative pin fingerprint.",
            "evidence": [],
        }

    evidence = []
    connected_nc_pins = []
    comparable = 0
    declared_matches = 0
    compiled_matches = 0

    for pin, obs in observed_pins.items():
        actual = pin_key(obs.get("name") or obs.get("pin_name"))
        if not actual:
            continue
        dp = norm(declared_profile["pins"].get(str(pin)))
        cp = norm(compiled_profile["pins"].get(str(pin)))
        if not dp and not cp:
            continue
        comparable += 1
        if dp == actual:
            declared_matches += 1
        if cp == actual:
            compiled_matches += 1
        if (dp == "NC" and cp == "NC" and obs.get("net")):
            connected_nc_pins.append({"pin": str(pin), "net": obs.get("net")})
        evidence.append({
            "pin": str(pin),
            "observed": obs.get("name") or obs.get("pin_name"),
            "declared_expected": declared_profile["pins"].get(str(pin)),
            "compiled_expected": compiled_profile["pins"].get(str(pin)),
        })

    if declared_profile_override and effective_declared == declared and effective_declared != compiled:
        return {
            "state": "CONSISTENT",
            "reason": (
                "Explicit project identity authority selects declared profile %r; "
                "compiled library profile %r is retained as evidence but does not override "
                "the authorized physical part identity."
            ) % (effective_declared, compiled),
            "evidence": evidence,
            "identity_override": declared_profile_override,
            "connected_nc_pins": connected_nc_pins,
        }

    if effective_declared == compiled:
        return {
            "state": "CONSISTENT",
            "reason": ("Declared profile override %r matches compiled identity." % effective_declared)
                if declared_profile_override else "Declared and compiled identities match.",
            "evidence": evidence,
        }

    # Require enough observed pins to make the distinction authoritative.
    if comparable == 0:
        return {
            "state": "UNKNOWN",
            "reason": "No observed pin-function evidence is available to distinguish the identities.",
            "evidence": evidence,
        }

    if compiled_matches == comparable and declared_matches < comparable:
        return {
            "state": "CONTRADICTION",
            "reason": (
                "Observed compiled pin functions match the compiled-library "
                "profile and conflict with the declared-part profile."
            ),
            "evidence": evidence,
            "connected_nc_pins": connected_nc_pins,
            "declared_profile_source": declared_profile["source"],
            "compiled_profile_source": compiled_profile["source"],
        }

    if declared_matches == comparable and compiled_matches < comparable:
        return {
            "state": "CONTRADICTION",
            "reason": (
                "Observed pin functions match the declared-part profile and "
                "conflict with the compiled-library profile."
            ),
            "evidence": evidence,
            "declared_profile_source": declared_profile["source"],
            "compiled_profile_source": compiled_profile["source"],
        }

    return {
        "state": "UNKNOWN",
        "reason": "Observed pin functions do not uniquely identify either candidate.",
        "evidence": evidence,
        "connected_nc_pins": connected_nc_pins,
        "declared_profile_source": declared_profile["source"],
        "compiled_profile_source": compiled_profile["source"],
    }
