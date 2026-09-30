#!/usr/bin/env python3
"""Generic, deterministic PCB placement optimizer.

Consumes authoritative component positions/envelopes plus net-derived affinity.
It never knows project-specific references or nets and never mutates a PcbDoc.
The caller decides whether a candidate is authoritative enough to commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Dict, Iterable, Mapping, Sequence, Tuple

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]


@dataclass(frozen=True)
class PlacementNode:
    reference: str
    position: Point
    envelope: Box
    locked: bool = False


@dataclass(frozen=True)
class PlacementConfig:
    iterations: int = 24
    step_scales: Tuple[float, ...] = (1.0, 0.5, 0.25, 0.125)
    affinity_weight: float = 1.0
    overlap_penalty: float = 1_000_000.0
    board_penalty: float = 1_000_000.0
    movement_penalty: float = 0.02
    edge_penalty: float = 100.0
    edge_clearance_mils: float = 0.0


def _shift(box: Box, dx: float, dy: float) -> Box:
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


def _overlap(a: Box, b: Box) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _center(box: Box) -> Point:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _inside(box: Box, board: Box, clearance: float) -> bool:
    return (
        box[0] >= board[0] + clearance
        and box[1] >= board[1] + clearance
        and box[2] <= board[2] - clearance
        and box[3] <= board[3] - clearance
    )


def _edge_distance(box: Box, board: Box) -> float:
    return min(
        box[0] - board[0],
        box[1] - board[1],
        board[2] - box[2],
        board[3] - box[3],
    )


def score(
    positions: Mapping[str, Point],
    nodes: Mapping[str, PlacementNode],
    affinity: Mapping[Tuple[str, str], float],
    board: Box,
    config: PlacementConfig = PlacementConfig(),
) -> Dict[str, float]:
    wire = 0.0
    for (a, b), weight in affinity.items():
        if a in positions and b in positions:
            wire += max(float(weight), 0.0) * hypot(
                positions[a][0] - positions[b][0],
                positions[a][1] - positions[b][1],
            )

    overlaps = 0
    outside = 0
    edge_penalty = 0.0
    refs = sorted(nodes)
    for i, a in enumerate(refs):
        na = nodes[a]
        dx = positions[a][0] - na.position[0]
        dy = positions[a][1] - na.position[1]
        ba = _shift(na.envelope, dx, dy)
        if not _inside(ba, board, config.edge_clearance_mils):
            outside += 1
        edge_penalty += max(0.0, config.edge_clearance_mils - _edge_distance(ba, board))
        for b in refs[i + 1 :]:
            nb = nodes[b]
            dbx = positions[b][0] - nb.position[0]
            dby = positions[b][1] - nb.position[1]
            bb = _shift(nb.envelope, dbx, dby)
            if _overlap(ba, bb):
                overlaps += 1

    movement = sum(
        hypot(positions[r][0] - nodes[r].position[0], positions[r][1] - nodes[r].position[1])
        for r in refs
    )
    total = (
        config.affinity_weight * wire
        + config.overlap_penalty * overlaps
        + config.board_penalty * outside
        + config.movement_penalty * movement
        + config.edge_penalty * edge_penalty
    )
    return {
        "total": total,
        "wire_cost": wire,
        "overlap_count": float(overlaps),
        "outside_count": float(outside),
        "movement_mils": movement,
        "edge_penalty": edge_penalty,
    }


def optimize(
    nodes: Iterable[PlacementNode],
    affinity: Mapping[Tuple[str, str], float],
    board: Box,
    config: PlacementConfig = PlacementConfig(),
) -> Dict[str, object]:
    """Optimize movable components by deterministic coordinate descent.

    Candidate targets are generated from weighted affinity barycenters and
    bounded local offsets. Locked components are immutable. A candidate is
    accepted only when its scalar objective strictly improves.
    """
    node_map = {n.reference: n for n in nodes}
    positions = {r: n.position for r, n in node_map.items()}
    initial = score(positions, node_map, affinity, board, config)
    current = dict(positions)

    neighbors: Dict[str, list[Tuple[str, float]]] = {r: [] for r in node_map}
    for (a, b), weight in affinity.items():
        if a in neighbors and b in neighbors:
            w = max(float(weight), 0.0)
            neighbors[a].append((b, w))
            neighbors[b].append((a, w))

    for _ in range(max(1, config.iterations)):
        changed = False
        for ref in sorted(node_map):
            node = node_map[ref]
            if node.locked or not neighbors[ref]:
                continue
            sw = sum(w for _, w in neighbors[ref] if w > 0 and _ in current)
            if sw <= 0:
                continue
            tx = sum(current[o][0] * w for o, w in neighbors[ref] if o in current and w > 0) / sw
            ty = sum(current[o][1] * w for o, w in neighbors[ref] if o in current and w > 0) / sw
            base = current[ref]
            for scale in config.step_scales:
                target = (
                    base[0] + (tx - base[0]) * scale,
                    base[1] + (ty - base[1]) * scale,
                )
                trial = dict(current)
                trial[ref] = target
                if score(trial, node_map, affinity, board, config)["total"] < score(
                    current, node_map, affinity, board, config
                )["total"]:
                    current = trial
                    changed = True
                    break
        if not changed:
            break

    final = score(current, node_map, affinity, board, config)
    moves = []
    for ref in sorted(node_map):
        before = node_map[ref].position
        after = current[ref]
        distance = hypot(after[0] - before[0], after[1] - before[1])
        moves.append({
            "reference": ref,
            "current_mils": list(before),
            "suggested_target_mils": [round(after[0], 3), round(after[1], 3)],
            "move_distance_mils": round(distance, 3),
            "locked": node_map[ref].locked,
            "changed": distance > 1e-6,
        })

    return {
        "schema": "altium-placement-optimizer.v1",
        "status": "OPTIMIZED" if final["total"] < initial["total"] else "NO_IMPROVEMENT",
        "mutation": "FORBIDDEN",
        "objective": {
            "initial": initial,
            "final": final,
            "improved": final["total"] < initial["total"],
        },
        "moves": moves,
    }
