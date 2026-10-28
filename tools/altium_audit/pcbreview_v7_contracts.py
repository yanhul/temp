"""Fail-closed contract gates for PCB Review Stage 1 v7.

This module deliberately separates evidence status from parser output. It does not
claim that an Altium API, unit scale, net mapping, or outline is verified merely
because a code path was exercised.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping, Sequence

PARSER_VERSION = "pcbreview.parse/7.1"
REQUIRED_CONTRACTS = frozenset({
    "component_api",
    "pcbdoc_read",
    "pad_api",
    "pad_units",
    "component_index_mapping",
    "board_outline_api",
    "locked_flag",
    "netlist_names",
})
VERIFIED = "VERIFIED"


def contract_is_verified(status: object) -> bool:
    """Only the exact VERIFIED token passes; USED_*/VERIFIED_SOURCE never do."""
    return isinstance(status, str) and status.strip().upper() == VERIFIED


def all_contracts_verified(statuses: Mapping[str, object]) -> bool:
    """Fail closed on missing, unknown, inferred, or merely exercised contracts."""
    return set(statuses) >= REQUIRED_CONTRACTS and all(
        contract_is_verified(statuses.get(name)) for name in REQUIRED_CONTRACTS
    )


def normalize_polygon(points: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
    """Normalize a closed polygon, rejecting malformed/non-finite coordinates."""
    normalized: list[tuple[float, float]] = []
    for point in points:
        if len(point) != 2:
            raise ValueError("each polygon vertex must contain exactly x,y")
        x, y = float(point[0]), float(point[1])
        if not (isfinite(x) and isfinite(y)):
            raise ValueError("polygon coordinates must be finite")
        normalized.append((x, y))
    # Strip repeated closing vertices; they are implicit in polygon algorithms.
    while len(normalized) > 1 and normalized[-1] == normalized[0]:
        normalized.pop()
    if len(normalized) < 3:
        raise ValueError("polygon requires at least three distinct vertices")
    if len(set(normalized)) < 3:
        raise ValueError("polygon requires at least three distinct vertices")
    area2 = sum(
        normalized[i][0] * normalized[(i + 1) % len(normalized)][1]
        - normalized[(i + 1) % len(normalized)][0] * normalized[i][1]
        for i in range(len(normalized))
    )
    if not isfinite(area2) or abs(area2) <= 1e-12:
        raise ValueError("polygon area is zero or numerically invalid")
    return normalized


def resolve_mobility(
    *, source_locked: object = None, policy_override: object = None
) -> tuple[str, bool]:
    """Return (mobility, verified); policy override never masquerades as source data."""
    if isinstance(source_locked, bool):
        source_value = "FIXED" if source_locked else "MOVABLE"
        if policy_override is None:
            return source_value, True
    else:
        source_value = "UNKNOWN"
    if policy_override in ("FIXED", "MOVABLE"):
        return str(policy_override), False
    return source_value, isinstance(source_locked, bool)


@dataclass(frozen=True)
class Stage1Gate:
    contract_statuses: Mapping[str, object]
    pad_units_verified: bool
    net_names_verified: bool
    outline_verified: bool
    mobility_verified: bool

    @property
    def all_contracts_verified(self) -> bool:
        return all_contracts_verified(self.contract_statuses)

    @property
    def parse_status(self) -> str:
        return "PARSED_VERIFIED" if self.routing_ready else "PARSED_UNVERIFIED"

    @property
    def geometry_status(self) -> str:
        return "PASS" if self.outline_verified and self.pad_units_verified else "UNVERIFIED"

    @property
    def electrical_status(self) -> str:
        return "PASS" if self.net_names_verified and self.all_contracts_verified else "UNVERIFIED"

    @property
    def routing_ready(self) -> bool:
        return all((
            self.all_contracts_verified,
            self.pad_units_verified,
            self.net_names_verified,
            self.outline_verified,
            self.mobility_verified,
        ))
