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
    return n


def resolve_declared_vs_compiled(
    declared_value: str | None,
    compiled_library: str | None,
    observed_pins: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Return CONSISTENT, CONTRADICTION, or UNKNOWN.

    A library-name mismatch alone is evidence of contradiction only when the
    observed pin fingerprint also agrees with the compiled candidate. This
    avoids treating arbitrary symbol/library naming as proof of electrical
    identity.
    """
    declared = profile_key(declared_value)
    compiled = profile_key(compiled_library)
    observed_pins = observed_pins or {}

    if not declared or not compiled:
        return {
            "state": "UNKNOWN",
            "reason": "Declared value or compiled library identity is missing.",
            "evidence": [],
        }

    declared_profile = AUTHORITATIVE_PIN_PROFILES.get(declared)
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
        actual = norm(obs.get("name") or obs.get("pin_name"))
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

    if declared == compiled:
        return {
            "state": "CONSISTENT",
            "reason": "Declared and compiled identities match.",
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
