from __future__ import annotations

from math import isfinite
from typing import Annotated

from app.types import NodesDict, LinesDict, MembersDict, MemberInfo

# Atomic helpers (no underscores per style guide)

def almostEqual(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def segmentIntersectionXY(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
    tol: float = 1e-8,
) -> tuple[float, float, float, float] | None:
    """Return (x, y, t, u) for intersection of segments p1-p2 and q1-q2 or None.
    End point touching counts; robust to near parallel using tolerance.
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = q1
    x4, y4 = q2
    dxp = x2 - x1
    dyp = y2 - y1
    dxq = x4 - x3
    dyq = y4 - y3
    den = dxp * dyq - dyp * dxq
    if almostEqual(den, 0.0, tol):
        return None
    rx = x3 - x1
    ry = y3 - y1
    t = (rx * dyq - ry * dxq) / den
    u = (rx * dyp - ry * dxp) / den
    if (t < -tol) or (t > 1 + tol) or (u < -tol) or (u > 1 + tol):
        return None
    t = min(max(t, 0.0), 1.0)
    u = min(max(u, 0.0), 1.0)
    xi = x1 + t * dxp
    yi = y1 + t * dyp
    if not (isfinite(xi) and isfinite(yi)):
        return None
    return (xi, yi, t, u)


def findExistingNode(
    nodes: NodesDict,
    x: float,
    y: float,
    z: float,
    tol: float,
) -> int | None:
    for nid, nd in nodes.items():
        if abs(nd["x"] - x) <= tol and abs(nd["y"] - y) <= tol and abs(nd["z"] - z) <= tol:
            return nid
    return None


def connectLinesAtIntersections(
    nodes: NodesDict,
    lines: LinesDict,
    members: MembersDict,
    *,
    tol: Annotated[float, "tolerance for geometric comparisons"] = 1e-6,
) -> tuple[
    NodesDict,
    LinesDict,
    MembersDict,
    dict[int, list[int]],  # mother_to_children
    dict[int, int],        # child_to_mother
]:
    """Insert nodes at crossings and split lines; propagate member data to children.

    Returns new data structures plus mapping dictionaries.
    """
    new_nodes: NodesDict = {k: dict(v) for k, v in nodes.items()}
    new_lines: LinesDict = {k: dict(v) for k, v in lines.items()}
    new_members: MembersDict = {k: dict(v) for k, v in members.items()}

    mother_to_children: dict[int, list[int]] = {lid: [] for lid in new_lines}
    child_to_mother: dict[int, int] = {}

    next_node_id = max(new_nodes) + 1 if new_nodes else 1
    next_line_id = max(new_lines) + 1 if new_lines else 1

    splits_by_line: dict[int, list[tuple[float, int]]] = {
        lid: [(0.0, new_lines[lid]["Ni"]), (1.0, new_lines[lid]["Nj"])] for lid in new_lines
    }

    line_ids = list(new_lines.keys())
    n_lines = len(line_ids)

    for i in range(n_lines):
        lid_i = line_ids[i]
        li = new_lines[lid_i]
        Pi = new_nodes[li["Ni"]]
        Pj = new_nodes[li["Nj"]]
        p1 = (Pi["x"], Pi["y"])  # type: ignore[index]
        p2 = (Pj["x"], Pj["y"])  # type: ignore[index]
        zi = (Pi["z"] + Pj["z"]) * 0.5
        for j in range(i + 1, n_lines):
            lid_j = line_ids[j]
            lj = new_lines[lid_j]
            Qi = new_nodes[lj["Ni"]]
            Qj = new_nodes[lj["Nj"]]
            q1 = (Qi["x"], Qi["y"])  # type: ignore[index]
            q2 = (Qj["x"], Qj["y"])  # type: ignore[index]
            zj = (Qi["z"] + Qj["z"]) * 0.5
            if abs(zi - zj) > tol:
                continue
            hit = segmentIntersectionXY(p1, p2, q1, q2, tol=tol)
            if not hit:
                continue
            xi, yi, ti, uj = hit
            zi_use = (zi + zj) * 0.5
            existing = findExistingNode(new_nodes, xi, yi, zi_use, tol=1e-6)
            if existing is None:
                nid = next_node_id
                next_node_id += 1
                new_nodes[nid] = {"id": nid, "x": float(xi), "y": float(yi), "z": float(zi_use)}
            else:
                nid = existing
            splits_by_line[lid_i].append((ti, nid))
            splits_by_line[lid_j].append((uj, nid))

    mothers_to_remove: list[int] = []
    for lid, param_nodes in splits_by_line.items():
        param_nodes = sorted(param_nodes, key=lambda tn: tn[0])
        dedup: list[tuple[float, int]] = []
        for t, nid in param_nodes:
            if not dedup or nid != dedup[-1][1]:
                dedup.append((t, nid))
        if len(dedup) <= 2:
            mother_to_children[lid].append(lid)
            child_to_mother[lid] = lid
            continue
        mothers_to_remove.append(lid)
        mother_member: MemberInfo | None = None
        for mid, m in list(new_members.items()):
            if m["line_id"] == lid:
                mother_member = m
                del new_members[mid]
                break
        for k in range(len(dedup) - 1):
            nid_a = dedup[k][1]
            nid_b = dedup[k + 1][1]
            if nid_a == nid_b:
                continue
            child_id = next_line_id
            next_line_id += 1
            new_lines[child_id] = {"id": child_id, "Ni": nid_a, "Nj": nid_b}
            mother_to_children[lid].append(child_id)
            child_to_mother[child_id] = lid
            if mother_member is not None:
                new_members[child_id] = {
                    "line_id": child_id,
                    "cross_section_id": mother_member["cross_section_id"],
                    "material_name": mother_member["material_name"],
                }
    for lid in mothers_to_remove:
        if lid in new_lines:
            del new_lines[lid]
    for lid in list(lines.keys()):
        if lid not in mother_to_children:
            mother_to_children[lid] = []
        if not mother_to_children[lid] and lid in new_lines:
            mother_to_children[lid] = [lid]
            child_to_mother[lid] = lid
    return new_nodes, new_lines, new_members, mother_to_children, child_to_mother

# Backwards-compatible alias requested by existing code
connect_lines_at_intersections = connectLinesAtIntersections

__all__ = [
    "almostEqual",
    "segmentIntersectionXY",
    "findExistingNode",
    "connectLinesAtIntersections",
    "connect_lines_at_intersections",
]
