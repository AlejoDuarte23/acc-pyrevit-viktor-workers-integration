import json
from io import BytesIO
from pathlib import Path
from typing import Tuple, Dict, Any

import app.aps_helpers as aps_helpers
from app.steps import step
from viktor.core import File
from viktor.external.python import PythonAnalysis


@step("pull_revit_file")
def pull_revit_file_from_acc(token: str, urn: str, viewable_dict: Dict[str, Dict[str, Any]]) -> Tuple[str, bytes]:
    """Find metadata for `urn` in `viewable_dict`, download the file and return
    a safe filename and raw bytes.

    viewable_dict is the same shape as returned by `get_viewable_files_dict` in
    `app.py` (mapping name -> meta dict containing 'urn', 'project_id', 'item_id').

    Raises FileNotFoundError or RuntimeError on failure.
    """
    if not urn:
        raise ValueError("URN is empty")

    # Locate metadata to fetch file content
    meta = None
    file_name = None
    for name, m in viewable_dict.items():
        if m.get("urn") == urn:
            meta = m
            file_name = name
            break

    if not meta or not file_name:
        raise FileNotFoundError("Could not resolve metadata for selected URN")

    project_id = meta.get("project_id")
    item_id = meta.get("item_id")
    if not (project_id and item_id):
        raise RuntimeError("Missing project_id or item_id in metadata")

    raw_bytes = aps_helpers.get_file_content(token, project_id, item_id)
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise RuntimeError("Downloaded file content is not bytes")

    safe_name = file_name.replace("/", "_").replace("\\", "_")
    if not safe_name.lower().endswith(".rvt"):
        safe_name += ".rvt"

    # Persist locally (optional) for debugging
    try:
        output_dir = Path(__file__).parent / "downloaded_files"
        output_dir.mkdir(exist_ok=True)
        rvt_path = output_dir / safe_name
        rvt_path.write_bytes(raw_bytes)
    except Exception:
        # best effort - don't fail the flow because of disk writes
        pass

    return safe_name, bytes(raw_bytes)


@step("run_revit_worker")
def run_revit_worker(safe_name: str, raw_bytes: bytes, script_path: Path | None = None, timeout: int = 600) -> dict:
    """Run the PythonAnalysis worker `revit_worker.py` on the provided RVT bytes
    and return the parsed output.json as a dict.

    Raises RuntimeError on failures.
    """
    if script_path is None:
        script_path = Path(__file__).parent / "revit_worker.py"

    if not script_path.exists():
        raise FileNotFoundError("Worker script revit_worker.py missing")

    script = File.from_path(script_path)
    model_files = [(safe_name, BytesIO(raw_bytes))]

    revit_analysis = PythonAnalysis(script=script, files=model_files, output_filenames=["output.json"])  # type: ignore[arg-type]
    revit_analysis.execute(timeout=timeout)

    output_file_obj = revit_analysis.get_output_file("output.json")
    if output_file_obj is None:
        raise RuntimeError("revit worker did not produce output.json")

    # Many SDK file-like objects expose getvalue(); try common accessors
    contents = None
    for attempt in ("getvalue", "get_bytes", "read", "read_bytes"):
        func = getattr(output_file_obj, attempt, None)
        if callable(func):
            try:
                contents = func()
            except TypeError:
                try:
                    contents = func(binary=True)
                except Exception:
                    try:
                        contents = func(as_bytes=True)
                    except Exception:
                        continue
            except Exception:
                continue
        if contents is not None:
            break

    if contents is None:
        raise RuntimeError("Could not read output.json from worker result")

    if isinstance(contents, (bytes, bytearray)):
        text = contents.decode("utf-8", errors="ignore")
    else:
        text = str(contents)

    try:
        output_json = json.loads(text)
    except Exception as e:
        raise RuntimeError(f"Unable to parse output.json: {e}")

    # Persist for debugging
    try:
        out_dir = Path(__file__).parent / "downloaded_files"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "output.json").write_text(json.dumps(output_json, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return output_json


@step("parse_revit_model")
def parse_revit_model(output_json: dict) -> Tuple[dict, dict, dict, dict]:
    """Parse the worker output into nodes, lines, cross_sections and members dicts.

    Returns (nodes, lines, cross_sections, members)
    """
    members_raw = output_json.get("analytical_members") or output_json.get("members") or []
    if not members_raw:
        raise ValueError("No members found in analysis output")

    try:
        from app.types import (
            NodeInfo,
            LineInfo,
            CrossSectionInfo,
            MemberInfo,
            NodesDict,
            LinesDict,
            CrossSectionsDict,
            MembersDict,
        )
    except Exception as e:
        raise RuntimeError(f"Failed importing types: {e}")

    nodes: NodesDict = {}
    lines: LinesDict = {}
    cross_sections: CrossSectionsDict = {}
    members: MembersDict = {}

    for idx, m in enumerate(members_raw):
        try:
            member_id = int(m.get("id", idx))
            node_i_id = int(m.get("nodeI"))
            node_j_id = int(m.get("nodeJ"))
            endpoints = m.get("endpoints", {})
            coord_i = endpoints.get("i") or endpoints.get("I") or [0, 0, 0]
            coord_j = endpoints.get("j") or endpoints.get("J") or [0, 0, 0]
            if node_i_id not in nodes:
                nodes[node_i_id] = NodeInfo(id=node_i_id, x=float(coord_i[0]), y=float(coord_i[1]), z=float(coord_i[2]))
            if node_j_id not in nodes:
                nodes[node_j_id] = NodeInfo(id=node_j_id, x=float(coord_j[0]), y=float(coord_j[1]), z=float(coord_j[2]))
            line_id = member_id
            lines[line_id] = LineInfo(id=line_id, Ni=node_i_id, Nj=node_j_id)
            section = m.get("section", {})
            section_props = m.get("section_properties", {})
            cs_id = int(section.get("type_id", member_id))
            if cs_id not in cross_sections:
                height = section_props.get("STRUCTURAL_SECTION_COMMON_HEIGHT") or section_props.get("HEIGHT") or 0.3
                width = section_props.get("STRUCTURAL_SECTION_COMMON_WIDTH") or section_props.get("WIDTH") or height
                area = section_props.get("STRUCTURAL_SECTION_AREA") or 0.01
                iz = section_props.get("STRUCTURAL_SECTION_COMMON_MOMENT_OF_INERTIA_STRONG_AXIS") or 1e-4
                iy = section_props.get("STRUCTURAL_SECTION_COMMON_MOMENT_OF_INERTIA_WEAK_AXIS") or 1e-5
                jxx = section_props.get("STRUCTURAL_SECTION_COMMON_TORSIONAL_MOMENT_OF_INERTIA") or 1e-6
                cross_sections[cs_id] = CrossSectionInfo(
                    id=cs_id,
                    name=section.get("type_name") or section.get("family_name") or "Section",
                    A=float(area),
                    Iz=float(iz),
                    Iy=float(iy),
                    Jxx=float(jxx),
                    b=float(width),
                    h=float(height),
                )
            members[member_id] = MemberInfo(line_id=line_id, cross_section_id=cs_id, material_name="Steel")
        except Exception:
            # skip problematic members
            continue

    return nodes, lines, cross_sections, members
