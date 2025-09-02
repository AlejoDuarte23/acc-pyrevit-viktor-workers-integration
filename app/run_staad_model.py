import subprocess
import time
import json 
import comtypes.client

from pythoncom import CoInitialize, CoUninitialize
from datetime import datetime
from pathlib import Path


import ctypes
from comtypes import automation
from comtypes.automation import VT_R8


from typing import Annotated, TypedDict, Literal, Any


def make_variant_vt_ref(obj: Any, var_type: int) -> automation.VARIANT:
    """Wraps an object in a VARIANT with VT_BYREF flag."""
    var = automation.VARIANT()
    var._.c_void_p = ctypes.addressof(obj)
    var.vt = var_type | automation.VT_BYREF
    return var


class NodeInfo(TypedDict):
    id: int
    x: float
    y: float
    z: float


class LineInfo(TypedDict):
    id: int
    Ni: int
    Nj: int

NodesDict = dict[str, NodeInfo]
LinesDict = dict[str, LineInfo]

class MemberInfo(TypedDict):
    line_id: int
    cross_section_id: int
    material_name: Literal["Concrete", "Steel"]

class CrossSectionInfo(TypedDict):
    name: str
    id: int
    A: Annotated[float, "Area"]
    Iz: Annotated[float, "Inertia around z, Strong Axis"]
    Iy: Annotated[float, "Inertia around y, Weak Axis"]
    Jxx: Annotated[float, "Torsional Inertia"]
    b: Annotated[float, "Section width"]
    h: Annotated[float, "Section height"]


SecNameToIDLookUp = dict[Annotated[str, "CS Name"], Annotated[int, "CS STADD ID"]]
# Since json doesnt allow int as keys we get str as keys!
CrossSectionsDict = dict[str, CrossSectionInfo]
MembersDict = dict[str, MemberInfo]


def get_max_section_displacement(
    openstaad: Annotated[Any, 'OpenSTAADOutput instance.'],
    member_id: Annotated[int, 'Member identifier.'],
    load_case: Annotated[int, 'Load case identifier.'],
    direction: Annotated[int, 'Global direction (X=1, Y=2, Z=3).']
) -> tuple[float, float]:
    """Backward-compatible helper that calls the OpenSTAAD Output.GetMaxSectionDisplacement API.

    Returns (max_disp, max_disp_position).
    """
    output = openstaad.Output
    max_disp = ctypes.c_double()
    max_disp_pos = ctypes.c_double()
    output._FlagAsMethod("GetMaxSectionDisplacement")
    variant_max_disp = make_variant_vt_ref(max_disp, VT_R8)
    variant_max_disp_pos = make_variant_vt_ref(max_disp_pos, VT_R8)
    # Map numeric direction to STAAD axis letter
    dir_map = {1: "X", 2: "Y", 3: "Z"}
    axis = dir_map.get(direction, "Y")
    output.GetMaxSectionDisplacement(member_id, axis, load_case, variant_max_disp, variant_max_disp_pos)
    return max_disp.value, max_disp_pos.value

def saelect_optimal_section():
    # for each iteration get al get_min_max
    # get the min out of all iterations 
    # return the optimal cross section to viktor
    return None

def create_members_cross_section(staad_property:Any, membes_dict: MembersDict, cs_dict: CrossSectionsDict) -> SecNameToIDLookUp:
    """Backward-compatible helper that creates beam properties in OpenSTAAD and returns a name->property-id map."""
    country_code = 3  # UK database.
    type_spec = 0      # ST (Single Section from Table).
    add_spec_1 = 0.0
    add_spec_2 = 0.0
    unique_cs = set()
    sect_name_id: SecNameToIDLookUp = {}
    for _, vals in membes_dict.items():
        cs_id = vals["cross_section_id"]
        cs_info = cs_dict[str(cs_id)]
        cs_name = cs_info["name"]
        if cs_name not in unique_cs:
            property_no = staad_property.CreateBeamPropertyFromTable(
                country_code, cs_name, type_spec, add_spec_1, add_spec_2
            )
            unique_cs.add(cs_name)
            sect_name_id[cs_name] = property_no
    return sect_name_id

member_displacements = dict[Annotated[int, "Member id"], Annotated[float, "Member max displacement Y dir"]]


def get_members_z_displacements(openstaad: Any, members_dict: MembersDict, case_num:int) -> dict:
    member_dispacement: member_displacements = {}
    for member_id in members_dict:
        max_disp, _ = get_max_section_displacement(
            openstaad=openstaad,
            member_id=int(member_id),
            load_case=case_num,
            direction=3,
        )
        member_dispacement[int(member_id)] = max_disp
    return member_dispacement


class STAADModel:
    """Encapsulates STAAD model creation, analysis and result extraction using OpenSTAAD.

    Methods are atomic so callers can run individual steps or the full workflow.
    """

    def __init__(
        self,
        nodes: NodesDict,
        lines: LinesDict,
        members: MembersDict,
        sections: CrossSectionsDict,
        staad_path: str | None = None,
        material_name: str = "STEEL",
    ) -> None:
        self.nodes = nodes
        self.lines = lines
        self.members = members
        self.sections = sections
        self.current_member_displacement: member_displacements = {}
        self.staad_path = (
            staad_path
            or r"C:\Program Files\Bentley\Engineering\STAAD.Pro 2025\STAAD\Bentley.Staad.exe"
        )
        self.material_name = material_name
        self.openstaad: Any | None = None
        self.staad_process: subprocess.Popen | None = None
        self.case_num: int | None = None

    def launch_and_connect(self) -> None:
        """Start STAAD.Pro and connect to OpenSTAAD COM object."""
        CoInitialize()
        self.staad_process = subprocess.Popen([self.staad_path])
        time.sleep(10)
        self.openstaad = comtypes.client.GetActiveObject("StaadPro.OpenSTAAD")
        # Ensure a few commonly-used members are flagged as methods so comtypes exposes them callable
        if self.openstaad:
            self.openstaad._FlagAsMethod("Analyze")
            self.openstaad._FlagAsMethod("isAnalyzing")
            self.openstaad._FlagAsMethod("SetSilentMode")
        else:
            raise Exception("Couldn't open STAAD")
        time.sleep(5)


    def new_staad_file(self, std_file_path: Path | None = None) -> Path:
        """Create a new STAAD file on disk and return its path."""
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M")
        std_file_path = std_file_path or (Path.cwd() / f"Structure_{timestamp}.std")
        length_unit = 4  # Meter
        force_unit = 5  # Kilo Newton
        assert self.openstaad is not None
        self.openstaad.NewSTAADFile(str(std_file_path), length_unit, force_unit)
        time.sleep(5)
        return std_file_path

    def set_material_name(self, material_name: str) -> None:
        assert self.openstaad is not None
        staad_property = self.openstaad.Property
        staad_property._FlagAsMethod("SetMaterialName")
        staad_property.SetMaterialName(material_name)

    def create_members_cross_section(self) -> SecNameToIDLookUp:
        assert self.openstaad is not None
        staad_property = self.openstaad.Property
        staad_property._FlagAsMethod("CreateBeamPropertyFromTable")
        return create_members_cross_section(staad_property, self.members, self.sections)

    def create_nodes_and_beams(self) -> None:
        """Create nodes and beam elements from the provided dictionaries and assign properties."""
        assert self.openstaad is not None
        geometry = self.openstaad.Geometry
        geometry._FlagAsMethod("CreateNode")
        geometry._FlagAsMethod("CreateBeam")
        staad_property = self.openstaad.Property
        staad_property._FlagAsMethod("AssignBeamProperty")

        cs_name2id_lookup = self.create_members_cross_section()

        created_nodes: set[str] = set()
        for line_id, vals in self.lines.items():
            Ni_id = str(vals["Ni"])
            Nj_id = str(vals["Nj"])
            Ni_cords = self.nodes[Ni_id]
            Nj_cords = self.nodes[Nj_id]
            if Ni_id not in created_nodes:
                # NOTE: original order was (id, x, z, y)
                geometry.CreateNode(int(Ni_id), Ni_cords["x"], Ni_cords["z"], Ni_cords["y"])
                created_nodes.add(Ni_id)
            if Nj_id not in created_nodes:
                geometry.CreateNode(int(Nj_id), Nj_cords["x"], Nj_cords["z"], Nj_cords["y"])
                created_nodes.add(Nj_id)
            geometry.CreateBeam(int(line_id), Ni_id, Nj_id)
            member_props = self.members[line_id]
            cs_info = self.sections[str(member_props["cross_section_id"]) ]
            staad_property.AssignBeamProperty(int(line_id), cs_name2id_lookup[cs_info["name"]])

    def add_support(self, nodes_with_support: list[int]) -> None:
        assert self.openstaad is not None
        support = self.openstaad.Support
        support._FlagAsMethod("CreateSupportFixed")
        support._FlagAsMethod("AssignSupportToNode")
        varnSupportNo = support.CreateSupportFixed()
        for node in nodes_with_support:
            support.AssignSupportToNode(node, varnSupportNo)

    def create_load_case(self) -> int:
        assert self.openstaad is not None
        load = self.openstaad.Load
        load._FlagAsMethod("SetLoadActive")
        load._FlagAsMethod("CreateNewPrimaryLoad")
        load._FlagAsMethod("AddSelfWeightInXYZ")
        case_num = load.CreateNewPrimaryLoad("Self Weight")
        ret = load.SetLoadActive(case_num)
        _ = load.AddSelfWeightInXYZ(2, -1.0)
        self.case_num = case_num
        return case_num

    def run_analysis(self, silent: bool = True, wait: bool = True) -> int:
        assert self.openstaad is not None
        command = self.openstaad.Command
        command._FlagAsMethod("PerformAnalysis")
        if silent:
            self.openstaad._FlagAsMethod("SetSilentMode")
            self.openstaad.SetSilentMode(1)
        command.PerformAnalysis(6)
        self.openstaad.SaveModel(1)
        # Trigger analysis and optionally wait
        # Flagging is done during connect; call Analyze and poll isAnalyzing() as a method
        self.openstaad.Analyze()
        if wait:
            while self.openstaad.isAnalyzing():
                time.sleep(2)
        return 0

    def get_member_max_displacement(self, member_id: int, load_case: int, direction: int = 3) -> tuple[float, float]:
        assert self.openstaad is not None
        return get_max_section_displacement(self.openstaad, member_id, load_case, direction)

    def get_member_max_displacements(self, load_case: int) -> member_displacements:
        assert self.openstaad is not None
        out: member_displacements = {}
        for member_id in self.members:
            max_disp, _ = self.get_member_max_displacement(int(member_id), load_case, direction=3)
            out[int(member_id)] = max_disp
        self.current_member_displacement = out
        return out

def run_staad():
    # Load lines and nodes from the downloaded_files folder next to this script.
    # Prefer the script-relative path, but fall back to the current working directory if necessary.
    script_dir = Path(__file__).resolve().parent
    input_json = script_dir / "downloaded_files" / "STAAD_inputs.json"
    if not input_json.exists():
        alt = Path.cwd() / "STAAD_inputs.json"
        if alt.exists():
            input_json = alt
        else:
            raise FileNotFoundError(
                f"STAAD inputs JSON not found at '{input_json}' nor at '{alt}'."
            )

    with open(input_json, "r", encoding="utf-8") as jsonfile:
        loaded = json.load(jsonfile)

    # Expecting a JSON array: [nodes, lines, section_name, member_dict, cross_section_dict]
    try:
        nodes, lines, section_name, member_dict, cross_section_dict = loaded
    except Exception as exc:
        raise ValueError(
            f"Unexpected STAAD_inputs.json structure: expected 5 items (nodes, lines, section_name, member_dict, cross_section_dict). Got: {type(loaded)}"
        ) from exc

    # Create STAAD model wrapper and run end-to-end
    model = STAADModel(nodes=nodes, lines=lines, members=member_dict, sections=cross_section_dict)
    model.launch_and_connect()
    model.new_staad_file(std_file_path=None)
    model.set_material_name("STEEL")
    model.create_nodes_and_beams()
    # Hard-coded supports from previous script (kept for compatibility)
    nodes_with_support = [431746, 431742, 431740, 431744]
    model.add_support(nodes_with_support)
    case_num = model.create_load_case()
    model.run_analysis(silent=True, wait=True)

    iteration_list = []
    member_y_displacement = model.get_member_max_displacements(load_case=case_num)
    iteration_list.append(member_y_displacement)

    json_path = Path.cwd() / "STAAD_output.json"
    with open(json_path, "w") as jsonfile:
        json.dump({"iterations": iteration_list}, jsonfile)

    CoUninitialize()
    return 0

if __name__ == "__main__":
    openstaad = run_staad()