# from __future__ import annotations

# from math import isfinite
# from typing import Annotated

# from app.app_types import (
#     NodesDict,
#     LinesDict,
#     MembersDict,
#     MemberInfo,
#     MotherToChildrenMap,
#     ChildToMotherMap,
# )


# # Atomic helpers
# def almostEqual(a: float, b: float, tol: float) -> bool:
#     return abs(a - b) <= tol


# def segmentIntersectionXY(
#     p1: tuple[float, float],
#     p2: tuple[float, float],
#     q1: tuple[float, float],
#     q2: tuple[float, float],
#     tol: float = 1e-8,
# ) -> tuple[float, float, float, float] | None:
#     x1, y1 = p1
#     x2, y2 = p2
#     x3, y3 = q1
#     x4, y4 = q2
#     dxp = x2 - x1
#     dyp = y2 - y1
#     dxq = x4 - x3
#     dyq = y4 - y3
#     den = dxp * dyq - dyp * dxq
#     if almostEqual(den, 0.0, tol):
#         return None
#     rx = x3 - x1
#     ry = y3 - y1
#     t = (rx * dyq - ry * dxq) / den
#     u = (rx * dyp - ry * dxp) / den
#     if (t < -tol) or (t > 1 + tol) or (u < -tol) or (u > 1 + tol):
#         return None
#     t = min(max(t, 0.0), 1.0)
#     u = min(max(u, 0.0), 1.0)
#     xi = x1 + t * dxp
#     yi = y1 + t * dyp
#     if not (isfinite(xi) and isfinite(yi)):
#         return None
#     return (xi, yi, t, u)


# def findExistingNode(
#     nodes: NodesDict,
#     x: float,
#     y: float,
#     z: float,
#     tol: float,
# ) -> int | None:
#     for nid, nd in nodes.items():
#         if abs(nd["x"] - x) <= tol and abs(nd["y"] - y) <= tol and abs(nd["z"] - z) <= tol:
#             return nid
#     return None


# def cloneNodes(nodes: NodesDict) -> NodesDict:
#     return {k: {"id": v["id"], "x": v["x"], "y": v["y"], "z": v["z"]} for k, v in nodes.items()}


# def cloneLines(lines: LinesDict) -> LinesDict:
#     return {k: {"id": v["id"], "Ni": v["Ni"], "Nj": v["Nj"]} for k, v in lines.items()}


# def cloneMembers(members: MembersDict) -> MembersDict:
#     return {
#         k: {
#             "line_id": v["line_id"],
#             "cross_section_id": v["cross_section_id"],
#             "material_name": v["material_name"],
#         }
#         for k, v in members.items()
#     }


# def initSplitParams(new_lines: LinesDict) -> dict[int, list[tuple[float, int]]]:
#     return {lid: [(0.0, info["Ni"]), (1.0, info["Nj"])] for lid, info in new_lines.items()}


# def collectIntersections(
#     new_nodes: NodesDict,
#     new_lines: LinesDict,
#     splits_by_line: dict[int, list[tuple[float, int]]],
#     tol: float,
#     next_node_id: int,
# ) -> int:
#     line_ids = list(new_lines.keys())
#     n_lines = len(line_ids)
#     for i in range(n_lines):
#         lid_i = line_ids[i]
#         li = new_lines[lid_i]
#         Pi = new_nodes[li["Ni"]]
#         Pj = new_nodes[li["Nj"]]
#         p1 = (Pi["x"], Pi["y"])  # type: ignore[index]
#         p2 = (Pj["x"], Pj["y"])  # type: ignore[index]
#         zi = (Pi["z"] + Pj["z"]) * 0.5
#         for j in range(i + 1, n_lines):
#             lid_j = line_ids[j]
#             lj = new_lines[lid_j]
#             Qi = new_nodes[lj["Ni"]]
#             Qj = new_nodes[lj["Nj"]]
#             q1 = (Qi["x"], Qi["y"])  # type: ignore[index]
#             q2 = (Qj["x"], Qj["y"])  # type: ignore[index]
#             zj = (Qi["z"] + Qj["z"]) * 0.5
#             if abs(zi - zj) > tol:
#                 continue
#             hit = segmentIntersectionXY(p1, p2, q1, q2, tol=tol)
#             if not hit:
#                 continue
#             xi, yi, ti, uj = hit
#             zi_use = (zi + zj) * 0.5
#             existing = findExistingNode(new_nodes, xi, yi, zi_use, tol=1e-6)
#             if existing is None:
#                 nid = next_node_id
#                 next_node_id += 1
#                 new_nodes[nid] = {"id": nid, "x": float(xi), "y": float(yi), "z": float(zi_use)}
#             else:
#                 nid = existing
#             splits_by_line[lid_i].append((ti, nid))
#             splits_by_line[lid_j].append((uj, nid))
#     return next_node_id


# def buildChildren(
#     new_lines: LinesDict,
#     new_members: MembersDict,
#     splits_by_line: dict[int, list[tuple[float, int]]],
#     next_line_id: int,
# ) -> tuple[LinesDict, MembersDict, MotherToChildrenMap, ChildToMotherMap, int]:
#     mother_to_children: MotherToChildrenMap = {lid: [] for lid in new_lines}  # type: ignore[assignment]
#     child_to_mother: ChildToMotherMap = {}  # type: ignore[assignment]
#     mothers_to_remove: list[int] = []
#     for lid, param_nodes in splits_by_line.items():
#         param_nodes = sorted(param_nodes, key=lambda tn: tn[0])
#         dedup: list[tuple[float, int]] = []
#         for t, nid in param_nodes:
#             if not dedup or nid != dedup[-1][1]:
#                 dedup.append((t, nid))
#         if len(dedup) <= 2:
#             mother_to_children[lid].append(lid)
#             child_to_mother[lid] = lid
#             continue
#         mothers_to_remove.append(lid)
#         mother_member: MemberInfo | None = None
#         for mid, m in list(new_members.items()):
#             if m["line_id"] == lid:
#                 mother_member = m
#                 del new_members[mid]
#                 break
#         for k in range(len(dedup) - 1):
#             nid_a = dedup[k][1]
#             nid_b = dedup[k + 1][1]
#             if nid_a == nid_b:
#                 continue
#             child_id = next_line_id
#             next_line_id += 1
#             new_lines[child_id] = {"id": child_id, "Ni": nid_a, "Nj": nid_b}
#             mother_to_children[lid].append(child_id)
#             child_to_mother[child_id] = lid
#             if mother_member is not None:
#                 new_members[child_id] = {
#                     "line_id": child_id,
#                     "cross_section_id": mother_member["cross_section_id"],
#                     "material_name": mother_member["material_name"],
#                 }
#     for lid in mothers_to_remove:
#         if lid in new_lines:
#             del new_lines[lid]
#     return new_lines, new_members, mother_to_children, child_to_mother, next_line_id


# def finalizeMappings(
#     original_lines: LinesDict,
#     new_lines: LinesDict,
#     mother_to_children: MotherToChildrenMap,
#     child_to_mother: ChildToMotherMap,
# ) -> None:
#     for lid in list(original_lines.keys()):
#         if lid not in mother_to_children:
#             mother_to_children[lid] = []  # type: ignore[index]
#         if not mother_to_children[lid] and lid in new_lines:
#             mother_to_children[lid] = [lid]  # type: ignore[index]
#             child_to_mother[lid] = lid  # type: ignore[index]


# def connect_lines_at_intersections(
#     nodes: NodesDict,
#     lines: LinesDict,
#     members: MembersDict,
#     *,
#     tol: Annotated[float, "tolerance for geometric comparisons"] = 1e-6,
# ) -> tuple[
#     NodesDict,
#     LinesDict,
#     MembersDict,
#     MotherToChildrenMap,
#     ChildToMotherMap,
# ]:
#     new_nodes = cloneNodes(nodes)
#     new_lines = cloneLines(lines)
#     new_members = cloneMembers(members)
#     splits_by_line = initSplitParams(new_lines)
#     next_node_id = max(new_nodes) + 1 if new_nodes else 1
#     next_line_id = max(new_lines) + 1 if new_lines else 1
#     next_node_id = collectIntersections(new_nodes, new_lines, splits_by_line, tol, next_node_id)
#     new_lines, new_members, mother_to_children, child_to_mother, next_line_id = buildChildren(
#         new_lines, new_members, splits_by_line, next_line_id
#     )
#     finalizeMappings(lines, new_lines, mother_to_children, child_to_mother)
#     print(f"[DEBUG] {child_to_mother=}, {mother_to_children=}")
#     return new_nodes, new_lines, new_members, mother_to_children, child_to_mother
from __future__ import annotations

from math import isfinite
from typing import Annotated

from app.app_types import (
    NodesDict,
    LinesDict,
    MembersDict,
    MemberInfo,
    MotherToChildrenMap,
    ChildToMotherMap,
)

# -------------------------------
# Atomic helpers
# -------------------------------

def almostEqual(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def segmentIntersectionXY(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
    tol: float = 1e-8,
) -> tuple[float, float, float, float] | None:
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
    # use provided tolerance for all axes
    for nid, nd in nodes.items():
        if abs(nd["x"] - x) <= tol and abs(nd["y"] - y) <= tol and abs(nd["z"] - z) <= tol:
            return nid
    return None


def cloneNodes(nodes: NodesDict) -> NodesDict:
    return {k: {"id": v["id"], "x": v["x"], "y": v["y"], "z": v["z"]} for k, v in nodes.items()}


def cloneLines(lines: LinesDict) -> LinesDict:
    return {k: {"id": v["id"], "Ni": v["Ni"], "Nj": v["Nj"]} for k, v in lines.items()}


def cloneMembers(members: MembersDict) -> MembersDict:
    return {
        k: {
            "line_id": v["line_id"],
            "cross_section_id": v["cross_section_id"],
            "material_name": v["material_name"],
        }
        for k, v in members.items()
    }


def initSplitParams(new_lines: LinesDict) -> dict[int, list[tuple[float, int]]]:
    return {lid: [(0.0, info["Ni"]), (1.0, info["Nj"])] for lid, info in new_lines.items()}

# -------------------------------
# Geometry helpers for collinearity and coverage
# -------------------------------

def _vec2(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (b[0] - a[0], b[1] - a[1])

def _cross2(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[1] - u[1] * v[0]

def _dot2(u: tuple[float, float], v: tuple[float, float]) -> float:
    return u[0] * v[0] + u[1] * v[1]

def _len2_sq(u: tuple[float, float]) -> float:
    return u[0] * u[0] + u[1] * u[1]

def collinearXY(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], tol: float) -> bool:
    # area of triangle abc close to zero
    return abs(_cross2(_vec2(a, b), _vec2(a, c))) <= tol

def pointParamOnSegmentXY(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> float:
    ab = _vec2(a, b)
    ap = _vec2(a, p)
    denom = _len2_sq(ab)
    if denom == 0.0:
        return 0.0
    return _dot2(ap, ab) / denom

def pointOnSegmentXY(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float], tol: float) -> bool:
    if not collinearXY(a, b, p, tol):
        return False
    t = pointParamOnSegmentXY(a, b, p)
    return -tol <= t <= 1.0 + tol

def sameElevation(z1: float, z2: float, tol: float) -> bool:
    return abs(z1 - z2) <= tol

# -------------------------------
# Core splitting
# -------------------------------

def collectIntersections(
    new_nodes: NodesDict,
    new_lines: LinesDict,
    splits_by_line: dict[int, list[tuple[float, int]]],
    tol: float,
    next_node_id: int,
) -> int:
    line_ids = list(new_lines.keys())
    n_lines = len(line_ids)
    # relax the plane check slightly to tolerate small modeling noise
    tol_z = max(tol, 10.0 * tol)
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
            if abs(zi - zj) > tol_z:
                continue
            hit = segmentIntersectionXY(p1, p2, q1, q2, tol=tol)
            if not hit:
                continue
            xi, yi, ti, uj = hit
            zi_use = (zi + zj) * 0.5
            existing = findExistingNode(new_nodes, xi, yi, zi_use, tol=tol)  # use tol
            if existing is None:
                nid = next_node_id
                next_node_id += 1
                new_nodes[nid] = {"id": nid, "x": float(xi), "y": float(yi), "z": float(zi_use)}
            else:
                nid = existing
            splits_by_line[lid_i].append((ti, nid))
            splits_by_line[lid_j].append((uj, nid))
    return next_node_id


def buildChildren(
    new_lines: LinesDict,
    new_members: MembersDict,
    splits_by_line: dict[int, list[tuple[float, int]]],
    next_line_id: int,
) -> tuple[LinesDict, MembersDict, MotherToChildrenMap, ChildToMotherMap, int]:
    mother_to_children: MotherToChildrenMap = {lid: [] for lid in new_lines}  # type: ignore[assignment]
    child_to_mother: ChildToMotherMap = {}  # type: ignore[assignment]
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
    return new_lines, new_members, mother_to_children, child_to_mother, next_line_id

# -------------------------------
# New, map pre existing segments onto mothers
# -------------------------------

def augmentMappingsWithExistingSegments(
    nodes: NodesDict,
    new_lines: LinesDict,
    mother_to_children: MotherToChildrenMap,
    child_to_mother: ChildToMotherMap,
    *,
    tol: float,
) -> None:
    """
    Attach any existing line as a child of a mother if:
      same elevation within tolerance,
      collinear in plan,
      both endpoints of the candidate lie on the mother span in plan.
    This does not delete or split geometry, it only updates the mappings.
    """
    # Pre compute endpoints and average z for speed
    endpoints_xy: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {}
    avg_z: dict[int, float] = {}
    for lid, ln in new_lines.items():
        ni = nodes[ln["Ni"]]
        nj = nodes[ln["Nj"]]
        endpoints_xy[lid] = ((ni["x"], ni["y"]), (nj["x"], nj["y"]))
        avg_z[lid] = 0.5 * (ni["z"] + nj["z"])

    # For every mother, scan all other lines
    for mother_id in list(mother_to_children.keys()):
        a, b = endpoints_xy.get(mother_id, ((0.0, 0.0), (0.0, 0.0)))
        z_m = avg_z.get(mother_id, 0.0)
        # ensure the mother maps to itself at least
        if mother_id not in mother_to_children:
            mother_to_children[mother_id] = []  # type: ignore[index]
        if mother_id not in mother_to_children[mother_id]:
            mother_to_children[mother_id].append(mother_id)
        if mother_id not in child_to_mother:
            child_to_mother[mother_id] = mother_id

        for cand_id, (c1, c2) in endpoints_xy.items():
            if cand_id == mother_id:
                continue
            # already mapped
            if cand_id in child_to_mother:
                continue
            # elevation check
            if not sameElevation(avg_z[cand_id], z_m, tol):
                continue
            # collinear and within span
            if not collinearXY(a, b, c1, tol) or not collinearXY(a, b, c2, tol):
                continue
            if not pointOnSegmentXY(a, b, c1, tol) or not pointOnSegmentXY(a, b, c2, tol):
                continue
            # looks like a true sub segment, attach it
            mother_to_children[mother_id].append(cand_id)
            child_to_mother[cand_id] = mother_id

# -------------------------------
# Finalization
# -------------------------------

def finalizeMappings(
    original_lines: LinesDict,
    new_lines: LinesDict,
    mother_to_children: MotherToChildrenMap,
    child_to_mother: ChildToMotherMap,
) -> None:
    for lid in list(original_lines.keys()):
        if lid not in mother_to_children:
            mother_to_children[lid] = []  # type: ignore[index]
        if not mother_to_children[lid] and lid in new_lines:
            mother_to_children[lid] = [lid]  # type: ignore[index]
            child_to_mother[lid] = lid  # type: ignore[index]

# -------------------------------
# Entry point
# -------------------------------

def connect_lines_at_intersections(
    nodes: NodesDict,
    lines: LinesDict,
    members: MembersDict,
    *,
    tol: Annotated[float, "tolerance for geometric comparisons"] = 1e-6,
) -> tuple[
    NodesDict,
    LinesDict,
    MembersDict,
    MotherToChildrenMap,
    ChildToMotherMap,
]:
    new_nodes = cloneNodes(nodes)
    new_lines = cloneLines(lines)
    new_members = cloneMembers(members)

    splits_by_line = initSplitParams(new_lines)
    next_node_id = max(new_nodes) + 1 if new_nodes else 1
    next_line_id = max(new_lines) + 1 if new_lines else 1

    next_node_id = collectIntersections(new_nodes, new_lines, splits_by_line, tol, next_node_id)
    new_lines, new_members, mother_to_children, child_to_mother, next_line_id = buildChildren(
        new_lines, new_members, splits_by_line, next_line_id
    )

    # NEW, attach pre existing sub segments like 433209–433216
    augmentMappingsWithExistingSegments(
        new_nodes, new_lines, mother_to_children, child_to_mother, tol=tol
    )

    finalizeMappings(lines, new_lines, mother_to_children, child_to_mother)

    print(f"[DEBUG] {child_to_mother=}, {mother_to_children=}")
    return new_nodes, new_lines, new_members, mother_to_children, child_to_mother
