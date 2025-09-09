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
    direction: Annotated[str, 'Global direction "X", "Y", "Z"']
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
    output.GetMaxSectionDisplacement(member_id, direction, load_case, variant_max_disp, variant_max_disp_pos)
    # By default staaad return the values in inch
    max_disp_value_mm = max_disp.value*25.4
    return max_disp_value_mm, max_disp_pos.value

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
            direction="Y",
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
        time.sleep(15)
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

    def add_support(self) -> None:
        assert self.openstaad is not None
        support = self.openstaad.Support
        support._FlagAsMethod("CreateSupportFixed")
        support._FlagAsMethod("AssignSupportToNode")
        varnSupportNo = support.CreateSupportFixed()
        min_z = min([vals["z"] for vals in self.nodes.values()])
        for node_id, vals in self.nodes.items():
            if vals["z"] == min_z:
                support.AssignSupportToNode(int(node_id), varnSupportNo)

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

    def create_point_loads(self, case_num: int, load_mag: float) -> None:
        load = self.openstaad.Load
        load._FlagAsMethod("AddNodalLoad")
        load._FlagAsMethod("SetLoadActive")
        ret = load.SetLoadActive(case_num) 
        for node_id, args in self.nodes.items():
            if args["z"] != 0:
                load.AddNodalLoad(int(node_id), 0, -load_mag, 0, 0, 0, 0)

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

    def get_member_max_displacement(self, member_id: int, load_case: int, direction: str) -> tuple[float, float]:
        assert self.openstaad is not None
        return get_max_section_displacement(self.openstaad, member_id, load_case, direction)

    def get_member_max_displacements(self, load_case: int) -> member_displacements:
        assert self.openstaad is not None
        out: member_displacements = {}
        for member_id in self.members:
            max_disp, _ = self.get_member_max_displacement(int(member_id), load_case, direction="Y")
            out[int(member_id)] = max_disp
        self.current_member_displacement = out
        return out

    def _find_section_id_by_name(self, section_name: str) -> int | None:
        """Return existing section id (int) for given section name or None."""
        for sid_str, info in self.sections.items():
            if info.get("name") == section_name:
                try:
                    return int(sid_str)
                except Exception:
                    continue
        return None

    def _add_dummy_section(self, section_name: str) -> int:
        """Add a CrossSectionInfo with dummy numeric attributes and return its new int id."""
        # choose new id as max existing + 1
        existing_ids = [int(k) for k in self.sections.keys()] if self.sections else []
        new_id = max(existing_ids) + 1 if existing_ids else 1
        info: CrossSectionInfo = {
            "name": section_name,
            "id": new_id,
            "A": 0.0,
            "Iz": 0.0,
            "Iy": 0.0,
            "Jxx": 0.0,
            "b": 0.2,
            "h": 0.2,
        }
        self.sections[str(new_id)] = info
        return new_id


def run_staad():
    input_json = Path.cwd() / "STAAD_inputs.json"
    with open(input_json) as jsonfile:
        loaded = json.load(jsonfile)

    # Expecting a JSON array: [nodes, lines, section_name, member_dict, cross_section_dict]
    nodes, lines, section_name, member_dict, cross_section_dict, allowable_disp, load_mag = loaded

    # Create STAAD model wrapper and run end-to-end
    model = STAADModel(nodes=nodes, lines=lines, members=member_dict, sections=cross_section_dict)
    model.launch_and_connect()
    model.new_staad_file(std_file_path=None)
    model.set_material_name("STEEL")
    model.create_nodes_and_beams()
    # Hard-coded supports from previous script (kept for compatibility)
    model.add_support()
    num_case = model.create_load_case()
    candidate_sections = [
        "UB254x102x28",
        "UB406x178x60",
        "UB533x210x92",
        "UB610x229x125",
        "UB1016x305x494",

    ]
    model.create_point_loads(case_num=num_case, load_mag=load_mag)
    model.run_analysis()
    member_displacement: dict[int, float] = {}
    for member_id in member_dict:
        max_disp, _ = model.get_member_max_displacement(member_id=member_id, load_case=num_case, direction="Y")
        member_displacement[member_id] = max_disp

    non_compliant_member = [member_id for member_id, disp in member_displacement.items() if abs(disp) > allowable_disp]

    def find_next_section(current_name: str, candidates: list[str]) -> str | None:
        try:
            idx = candidates.index(current_name)
            if idx + 1 < len(candidates):
                return candidates[idx + 1]
        except ValueError:
            if candidates:
                return candidates[0]
        return None

    while non_compliant_member:
        staad_property = model.openstaad.Property
        staad_property._FlagAsMethod("CreateBeamPropertyFromTable")
        staad_property._FlagAsMethod("AssignBeamProperty")
        for member_id in non_compliant_member:
            current_cs_id = member_dict[member_id]["cross_section_id"]
            current_cs_info = cross_section_dict[str(current_cs_id)]
            current_name = current_cs_info["name"]
            next_name = find_next_section(current_name, candidate_sections)
            if next_name is None:
                print(f"Member {member_id}: {current_name} has no more candidate sections. Still non-compliant.")
                continue
            print(f"Member {member_id}: {current_name} -> {next_name}")
            next_cs_id = model._find_section_id_by_name(next_name)
            if next_cs_id is None:
                staad_property.CreateBeamPropertyFromTable(3, next_name, 0, 0.0, 0.0)
                next_cs_id = model._add_dummy_section(next_name)
            member_dict[member_id]["cross_section_id"] = next_cs_id
            staad_property.AssignBeamProperty(int(member_id), next_cs_id)
        model.members = member_dict
        model.sections = cross_section_dict
        model.create_nodes_and_beams()
        model.add_support()
        if not num_case:
            num_case = model.create_load_case()
            model.create_point_loads(case_num=num_case, load_mag=load_mag)
        model.run_analysis()
        member_displacement = {}
        for member_id in member_dict:
            max_disp, _ = model.get_member_max_displacement(member_id=member_id, load_case=num_case, direction="Y")
            member_displacement[member_id] = max_disp
        non_compliant_member = [member_id for member_id, disp in member_displacement.items() if abs(disp) > allowable_disp]
        # Break if there are still non-compliant members after trying all candidate sections
        if any(find_next_section(cross_section_dict[str(member_dict[m]["cross_section_id"])] ["name"], candidate_sections) is None for m in non_compliant_member):
            print("Breaking: Some members remain non-compliant after all candidate sections.")
            break

    updated_member_dict = model.members
    updated_sections = model.sections
    updated_inputs = [
        updated_member_dict,
        updated_sections,
    ]
    json_path = Path.cwd() / "STAAD_output.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(updated_inputs, fh, indent=2)

    # Shutdown STAAD process if it was launched
    if hasattr(model, 'staad_process') and model.staad_process is not None:
        try:
            model.staad_process.terminate()
            model.staad_process.wait(timeout=10)
        except Exception as e:
            print(f"Failed to terminate STAAD process: {e}")
    openstaad = None
    CoUninitialize()
    return 0

if __name__ == "__main__":
    openstaad = run_staad()