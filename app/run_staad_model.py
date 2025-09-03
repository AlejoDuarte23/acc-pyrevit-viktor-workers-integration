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
    print(max_disp.value)
    print(max_disp_pos.value)
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

    def apply_section_to_all_members(self, section_name: str) -> None:
        """Set every member's cross_section_id to the id of section_name, adding the section if missing, then assign STAAD property."""
        assert self.openstaad is not None
        sid = self._find_section_id_by_name(section_name)
        if sid is None:
            sid = self._add_dummy_section(section_name)

        # update members in-memory
        for mid, mvals in self.members.items():
            mvals["cross_section_id"] = sid

        # create STAAD property and assign to members
        staad_property = self.openstaad.Property
        staad_property._FlagAsMethod("CreateBeamPropertyFromTable")
        country_code = 3
        type_spec = 0
        add_spec_1 = 0.0
        add_spec_2 = 0.0
        prop_no = staad_property.CreateBeamPropertyFromTable(country_code, section_name, type_spec, add_spec_1, add_spec_2)
        staad_property._FlagAsMethod("AssignBeamProperty")
        for line_id in self.members:
            staad_property.AssignBeamProperty(int(line_id), prop_no)

    def iterate_sections_and_choose_optimal(self, section_names: list[str]) -> tuple[dict[str, member_displacements], dict[str, MemberInfo]]:
        """Iterate over candidate section names, run analysis for each, collect displacements, and choose optimal section per member.

        Returns (results_by_section, final_members_dict) where results_by_section maps section_name to member displacement dict,
        and final_members_dict is the resulting members mapping with chosen cross_section_id per member.
        """
        assert self.openstaad is not None
        results: dict[str, member_displacements] = {}

        # ensure a single load case exists
        if self.case_num is None:
            self.create_load_case()
        case_num = self.case_num

        for sname in section_names:
            self.apply_section_to_all_members(sname)
            # run and collect
            self.run_analysis(silent=True, wait=True)
            disps = self.get_member_max_displacements(load_case=case_num)
            results[sname] = disps

        # choose best section per member (less negative = better -> maximize displacement value)
        final_members: dict[str, MemberInfo] = {}
        member_ids = sorted({int(k) for k in self.members.keys()})
        # ensure sections dict contains all tested sections
        for sname in section_names:
            if self._find_section_id_by_name(sname) is None:
                self._add_dummy_section(sname)

        # map section name to its id (int)
        secname2id: dict[str, int] = {sname: self._find_section_id_by_name(sname) for sname in section_names}

        for mid in member_ids:
            best_name = None
            best_val = float('-inf')
            for sname in section_names:
                val = results.get(sname, {}).get(mid)
                if val is None:
                    continue
                if val > best_val:
                    best_val = val
                    best_name = sname
            chosen_id = secname2id.get(best_name) if best_name is not None else self.members[str(mid)]["cross_section_id"]
            final_members[str(mid)] = {
                "line_id": mid,
                "cross_section_id": int(chosen_id),
                "material_name": self.members[str(mid)].get("material_name", "Steel"),
            }

        return results, final_members

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
    model.create_load_case()
    # Candidate cross-section names to try (you can change this list)
    candidate_sections = [
        "UB406x178x60",
        "UB254x102x8",
    ]

    results_by_section, final_members = model.iterate_sections_and_choose_optimal(candidate_sections)

    # Single combined output (legacy name)
    out_dir = Path.cwd()
    combined = {
        "section_displacements": results_by_section,
        "final_selection": {
            "members": final_members,
            "sections": model.sections,
        },
    }
    staad_output = out_dir / "STAAD_output.json"
    with open(staad_output, "w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=2)

    # Also write an updated STAAD inputs file with the same structure as the original inputs
    # Format: [nodes, lines, section_name, member_dict, cross_section_dict]
    updated_member_dict = final_members
    updated_sections = model.sections
    updated_inputs = [
        updated_member_dict,
        updated_sections,
    ]
    updated_inputs_path = out_dir / "STAAD_inputs_updated.json"
    with open(updated_inputs_path, "w", encoding="utf-8") as fh:
        json.dump(updated_inputs, fh, indent=2)

    CoUninitialize()
    return 0

if __name__ == "__main__":
    openstaad = run_staad()