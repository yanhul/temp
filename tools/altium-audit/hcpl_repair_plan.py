#!/usr/bin/env python3
"""HCPL topology repair-plan generation.

The planner is deliberately non-mutating. It converts observed canonical
schematic connectivity into an auditable plan and refuses to choose between
declared HCPL-0600 and compiled HCPL-3120 without explicit authority.
"""
from __future__ import annotations

HCPL_TOPOLOGY_MAP = {
    "U6": "UART_TX0", "U8": "UART_RX0",
    "U11": "UART_TX1", "U12": "UART_EN1", "U13": "UART_RX1",
    "U18": "ADC1_CLK", "U19": "ADC1_DATA", "U20": "ADC1_CS",
    "U23": "ADC2_CLK", "U24": "ADC2_DATA", "U25": "ADC2_CS",
    "U28": "ADC3_CLK", "U29": "ADC3_DATA", "U30": "ADC3_CS",
    "U33": "ADC4_CLK", "U34": "ADC4_DATA", "U35": "ADC4_CS",
}

def build_hcpl_repair_plan(records):
    by_ref = {str(c.get("reference")): c for c in (records or []) if c.get("reference")}
    groups = {}
    for ref, role in HCPL_TOPOLOGY_MAP.items():
        c = by_ref.get(ref)
        if not c:
            continue
        pins = {str(p.get("pin")): p for p in (c.get("pins") or [])}
        p4, p5, p6, p7, p8 = (pins.get(x) for x in ("4","5","6","7","8"))
        groups.setdefault(role, []).append({
            "ref": ref,
            "signal_pin6_net": (p6 or {}).get("connected_net"),
            "pin7_net": (p7 or {}).get("connected_net"),
            "pin4_net": (p4 or {}).get("connected_net"),
            "pin5_net": (p5 or {}).get("connected_net"),
            "pin8_net": (p8 or {}).get("connected_net"),
            "declared_value": c.get("declared_value"),
            "library_id": c.get("library_id"),
            "mpn": c.get("mpn"),
        })

    return {
        "schema": "hcpl-repair-plan.v1",
        "status": "AUTHORIZED_HCPL_0600",
        "identity_authority": {"part": "HCPL-0600", "authority": "USER_EXPLICIT"},
        "authority_required": "explicit_part_identity",
        "source_component": "HCPL-0600",
        "groups": groups,
        "rules": [
            "Do not mutate schematic until intended HCPL part is explicitly authorized.",
            "HCPL-0600 is authorized: pin 4 is NC; pin 6 is VO; pin 7 is VE/enable and must NOT be shorted to pin 6; VDD is 5 V. Verify the exact HCPL-0600 datasheet pinout and local bypass before mutation.",
            "Repair each observed illegal pin-4/pin-7 connection only after tracing its intended logical signal; do not blindly rewire to a guessed net.",
            "After any authorized wiring mutation: reparse compiled schematic, regenerate topology receipt, and rerun schematic CI before placement/routing."
        ]
    }
