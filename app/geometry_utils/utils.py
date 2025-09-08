import matplotlib
matplotlib.use("QtAgg", force=True)
import matplotlib.pyplot as plt
from collections import defaultdict
from math import sqrt
from app.app_types import NodesDict, LinesDict, Vec3

# Vector helpers
def v_sub(a: Vec3, b: Vec3) -> Vec3:
    """a - b"""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_cross(a: Vec3, b: Vec3) -> Vec3:
    """a × b"""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def v_norm(a: Vec3) -> float:
    """‖a‖₂"""
    return sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def clean_model(Nodes: dict, Lines: dict) -> tuple[dict, dict]:
    """Deletes duplicated nodes"""
    # Create a mapping from coordinates to node IDs
    coord_to_nodes = defaultdict(list)
    for node_id, attrs in Nodes.items():
        coord = (attrs["x"], attrs["y"], attrs["z"])
        coord_to_nodes[coord].append(node_id)

    # Identify duplicates: coordinates with more than one node ID
    duplicates = {coord: ids for coord, ids in coord_to_nodes.items() if len(ids) > 1}

    node_replacements = {}
    for _, ids in duplicates.items():
        kept_node = min(ids)  # Choose the node with the smallest ID to keep
        for duplicate_node in ids:
            if duplicate_node != kept_node:
                node_replacements[duplicate_node] = kept_node

    # Update Lines to replace deleted Nodes with Kept Nodes
    for line in Lines.values():
        if line["Ni"] in node_replacements:
            line["Ni"] = node_replacements[line["Ni"]]
        if line["Nj"] in node_replacements:
            line["Nj"] = node_replacements[line["Nj"]]

    # Remove duplicate Nodes
    for dup_node in node_replacements.keys():
        del Nodes[dup_node]

    return Nodes, Lines

def get_nodes_by_z(Nodes: dict, z: float) -> list[int]:
    selected = [node_id for node_id, attrs in Nodes.items() if attrs["z"] == z]
    return selected


def plot_model(nodes: NodesDict, lines: LinesDict) -> None:
    fig = plt.figure(figsize=(7, 5))
    ax = fig.add_subplot(111, projection="3d")

    # Draw nodes
    for nid, data in nodes.items():
        ax.scatter(data["x"], data["y"], data["z"])
        ax.text(data["x"], data["y"], data["z"], f"{nid}", fontsize=8, ha="center")

    # Draw lines
    # Precompute a small vertical offset for line labels to avoid overlap with the line itself
    if nodes:
        z_vals = [nd["z"] for nd in nodes.values()]
        z_range = max(z_vals) - min(z_vals) if len(z_vals) > 1 else 1.0
    else:
        z_range = 1.0
    z_off = 0.015 * z_range

    for line_id, line in lines.items():
        ni = nodes[line["Ni"]]
        nj = nodes[line["Nj"]]
        x_coords = [ni["x"], nj["x"]]
        y_coords = [ni["y"], nj["y"]]
        z_coords = [ni["z"], nj["z"]]
        ax.plot(x_coords, y_coords, z_coords)
        # Midpoint label
        mx = 0.5 * (x_coords[0] + x_coords[1])
        my = 0.5 * (y_coords[0] + y_coords[1])
        mz = 0.5 * (z_coords[0] + z_coords[1]) + z_off
        ax.text(mx, my, mz, f"L{line_id}", fontsize=7, ha="center", va="bottom", color="blue")

    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")  # Z is vertical
    ax.set_title("Platform Model / Node IDs and Connectivity")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    import json
    from app.steps import StepErrors
    from app.geometry_utils.connecte_intersetc_lines import connect_lines_at_intersections
    from app.conver_revit_model import parse_revit_model

    input_json_path = r"C:\Users\aleja\viktor-apps\revit-viktor-structural-worker\app\downloaded_files\output.json"
    with open(input_json_path, encoding="utf-8") as jsonfile:
        input_data = json.load(jsonfile)
    ctx = StepErrors()
    nodes, lines, cross_sections, members = parse_revit_model(output_json=input_data, _ctx=ctx)
    nodes2, lines2, members2, mother_to_children, child_to_mother = connect_lines_at_intersections(
        nodes, lines, members, tol=1e-6
    )
    plot_model(nodes=nodes2, lines=lines2)