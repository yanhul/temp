"""Small, fail-closed evidence graph prototype for reverse-engineering workflows.

This module records provenance; it does not perform decompilation or execute artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal

Status = Literal["OBSERVED", "INFERRED", "VERIFIED", "UNKNOWN", "CONTRADICTED"]
Kind = Literal["observation", "inference", "verification"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(ValueError):
    """Raised when evidence lineage or provenance is invalid."""


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    artifact_sha256: str
    kind: Kind
    status: Status
    claim: str
    source: str
    parent_ids: tuple[str, ...] = ()
    provider: str = ""
    environment_digest: str = ""


class EvidenceGraph:
    """Append-only evidence graph scoped to one immutable artifact digest."""

    def __init__(self, artifact_sha256: str) -> None:
        if not isinstance(artifact_sha256, str) or not _SHA256.fullmatch(artifact_sha256):
            raise EvidenceError("artifact_sha256 must be a lowercase SHA-256 digest")
        self.artifact_sha256 = artifact_sha256
        self._items: dict[str, Evidence] = {}

    @property
    def items(self) -> tuple[Evidence, ...]:
        return tuple(self._items.values())

    def add(self, item: Evidence) -> None:
        if not isinstance(item.evidence_id, str) or not item.evidence_id.strip() or item.evidence_id in self._items:
            raise EvidenceError("evidence_id must be non-empty and unique")
        if item.artifact_sha256 != self.artifact_sha256:
            raise EvidenceError("artifact digest mismatch; evidence belongs to another artifact")
        if not isinstance(item.claim, str) or not item.claim.strip() or not isinstance(item.source, str) or not item.source.strip():
            raise EvidenceError("claim and source are required")
        if item.kind not in ("observation", "inference", "verification"):
            raise EvidenceError("unsupported evidence kind")
        if item.status not in ("OBSERVED", "INFERRED", "VERIFIED", "UNKNOWN", "CONTRADICTED"):
            raise EvidenceError("unsupported evidence status")
        if not isinstance(item.parent_ids, tuple) or any(not isinstance(p, str) or not p.strip() for p in item.parent_ids):
            raise EvidenceError("parent_ids must be a tuple of non-empty evidence IDs")
        if len(set(item.parent_ids)) != len(item.parent_ids):
            raise EvidenceError("duplicate parent reference")
        missing = [parent for parent in item.parent_ids if parent not in self._items]
        if missing:
            raise EvidenceError(f"parents must exist before child evidence: {missing}")
        if item.kind == "observation" and item.status not in ("OBSERVED", "UNKNOWN", "CONTRADICTED"):
            raise EvidenceError("observations cannot assert inference or verification status")
        if item.kind == "inference" and item.status not in ("INFERRED", "UNKNOWN", "CONTRADICTED"):
            raise EvidenceError("inferences cannot self-promote to VERIFIED")
        if item.kind == "verification":
            if item.status not in ("VERIFIED", "UNKNOWN", "CONTRADICTED"):
                raise EvidenceError("verification status must be VERIFIED, UNKNOWN, or CONTRADICTED")
            if not item.environment_digest.strip():
                raise EvidenceError("verification requires an environment digest")
        if item.kind == "verification" and item.status == "VERIFIED":
            if not item.provider.strip():
                raise EvidenceError("VERIFIED requires a named verifier")
            if not item.parent_ids:
                raise EvidenceError("VERIFIED evidence must cite parent evidence")
            parents = [self._items[p] for p in item.parent_ids]
            if not any(
                parent.kind == "observation"
                and parent.status == "OBSERVED"
                and parent.claim == item.claim
                for parent in parents
            ):
                raise EvidenceError(
                    "VERIFIED evidence must cite an OBSERVED parent supporting the same claim"
                )
            if any(parent.status in ("UNKNOWN", "CONTRADICTED") and parent.claim == item.claim
                   for parent in parents):
                raise EvidenceError("VERIFIED evidence cannot cite unresolved or contradictory parent evidence")
        self._items[item.evidence_id] = item

    def terminal_state(self, required_claims: Iterable[str]) -> str:
        """PASS only if each required claim is verified and has no unresolved contradiction."""
        required = tuple(required_claims)
        if not required or any(not isinstance(claim, str) or not claim.strip() for claim in required):
            return "INCONCLUSIVE"
        for claim in required:
            claim_items = [item for item in self._items.values() if item.claim == claim]
            if any(item.status in ("CONTRADICTED", "UNKNOWN") for item in claim_items):
                return "INCONCLUSIVE"
            if not any(
                item.kind == "verification"
                and item.status == "VERIFIED"
                and item.artifact_sha256 == self.artifact_sha256
                for item in claim_items
            ):
                return "INCONCLUSIVE"
        return "PASS"

    def lineage(self, evidence_id: str) -> tuple[Evidence, ...]:
        """Return ancestors then the requested node; unknown IDs fail closed."""
        if evidence_id not in self._items:
            raise EvidenceError(f"unknown evidence_id: {evidence_id}")
        seen: set[str] = set()
        ordered: list[Evidence] = []

        def visit(current: str) -> None:
            if current in seen:
                return
            seen.add(current)
            item = self._items[current]
            for parent in item.parent_ids:
                visit(parent)
            ordered.append(item)

        visit(evidence_id)
        return tuple(ordered)
