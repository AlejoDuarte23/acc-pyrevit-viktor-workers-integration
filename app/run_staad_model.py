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

MemberType = Literal["Truss Diagonal", "Joist", "Beam", "Column", "Truss Chord"]
NodesDict = dict[int, NodeInfo]
LinesDict = dict[int, LineInfo]

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
    """Retrieve maximum section displacement in the specified global direction for a given member and load case.
    Returns a tuple containing the maximum displacement value and its corresponding position.
    """
    # Output instace
    output = openstaad.Output
    # Create ctypes double variables for maximum displacement and its position
    max_disp = ctypes.c_double()
    max_disp_pos = ctypes.c_double()

    # flag as method
    output._FlagAsMethod("GetMaxSectionDisplacement")
    # Wrap the c_double variables in VARIANTs using the provided helper function
    variant_max_disp = make_variant_vt_ref(max_disp, VT_R8)
    variant_max_disp_pos = make_variant_vt_ref(max_disp_pos, VT_R8)
    print(f"{member_id=}, {direction=}, {load_case=}")
    # Retrieve the maximum section displacement
    output.GetMaxSectionDisplacement(member_id, "Y", load_case, variant_max_disp, variant_max_disp_pos)
    print(max_disp)
    print(max_disp_pos)

    # Return the results with meaningful names
    return max_disp.value, max_disp_pos.value

def saelect_optimal_section():
    # for each iteration get al get_min_max
    # get the min out of all iterations 
    # return the optimal cross section to viktor
    return None

def create_members_cross_section(staad_property:Any, membes_dict: MembersDict, cs_dict: CrossSectionsDict) -> SecNameToIDLookUp:
    """Creates cross section based on the revit model, Only works for UK UB/UC beams/columns, return a look up
    section name vs section id"""
    # country_code = 7  # European database.
    country_code = 3  # UK database.  # noqa: F841 (retained for context/documentation)
    # section_name = "IPE400"  # Selected profile.
    type_spec = 0      # ST (Single Section from Table).  # noqa: F841
    add_spec_1 = 0.0   # Not used for single sections     # noqa: F841
    add_spec_2 = 0.0   # Must be 0.0.                     # noqa: F841
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
        print(max_disp)
        member_dispacement[int(member_id)] = max_disp
    return member_dispacement

def run_staad():
    CoInitialize()
    # Replace with your version and file path.
    staad_path = r"C:\Program Files\Bentley\Engineering\STAAD.Pro 2025\STAAD\Bentley.Staad.exe" 
    # Launch STAAD.Pro
    staad_process  = subprocess.Popen([staad_path])
    print("Launching STAAD.Pro...")
    time.sleep(15)
    # Connect to OpenSTAAD.
    openstaad = comtypes.client.GetActiveObject("StaadPro.OpenSTAAD")

    # Create a new STAAD file.
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M")
    std_file_path = Path.cwd() / f"Structure_{timestamp}.std" 
    length_unit = 4  # Meter.
    force_unit = 5  # Kilo Newton.
    openstaad.NewSTAADFile(str(std_file_path), length_unit, force_unit)

    # Load lines and nodes from the downloaded_files folder next to this script.
    # Prefer the script-relative path, but fall back to the current working directory if necessary.
    script_dir = Path(__file__).resolve().parent
    input_json = script_dir / "downloaded_files" / "STAAD_inputs.json"
    if not input_json.exists():
        # fallback: look in current working directory
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



    # Wait to load interface
    time.sleep(10)

    # Set Material and Beam Section
    staad_property = openstaad.Property
    staad_property._FlagAsMethod("SetMaterialName")
    staad_property._FlagAsMethod("CreateBeamPropertyFromTable")
    material_name = "STEEL"
    staad_property.SetMaterialName(material_name)

    # country_code = 7  # European database.
    country_code = 3  # UK database.
    # section_name = "IPE400"  # Selected profile.
    type_spec = 0  # ST (Single Section from Table).
    add_spec_1 = 0.0  # Not used for single sections
    add_spec_2 = 0.0  # Must be 0.0.

    
    cs_name2id_lookup: SecNameToIDLookUp = create_members_cross_section(staad_property=staad_property,
                                 membes_dict=member_dict,
                                 cs_dict=cross_section_dict)
    # Create Members.
    geometry = openstaad.Geometry
    geometry._FlagAsMethod("CreateNode")
    geometry._FlagAsMethod("CreateBeam")
    staad_property._FlagAsMethod("AssignBeamProperty")
    
    iteration_list = []
    ret: int | None = None
    for i in range(1):
        create_nodes = set()
        for line_id, vals in lines.items():
            Ni_id = str(vals["Ni"])
            Nj_id = str(vals["Nj"])
            Ni_cords = nodes[Ni_id]
            Nj_cords = nodes[Nj_id]
            if Ni_id not in create_nodes:
                geometry.CreateNode(int(Ni_id), Ni_cords["x"], Ni_cords["z"], Ni_cords["y"])
                create_nodes.add(Ni_id)
            if Nj_id not in create_nodes:
                geometry.CreateNode(int(Nj_id), Nj_cords["x"], Nj_cords["z"], Nj_cords["y"])
                create_nodes.add(Nj_id)
            geometry.CreateBeam(int(line_id), Ni_id, Nj_id)
            
            member_props = member_dict[line_id]
            cs_info = cross_section_dict[str(member_props["cross_section_id"])]
            # print(cs_info)
            # cs_name2id_lookup return the staad section id
            _ = staad_property.AssignBeamProperty(int(line_id), cs_name2id_lookup[cs_info["name"]])
        
        # Create supports.
        support = openstaad.Support
        support._FlagAsMethod("CreateSupportFixed")
        support._FlagAsMethod("AssignSupportToNode")

        varnSupportNo  = support.CreateSupportFixed()
        nodes_with_support = [431746, 431742, 431740, 431744]
        for node in nodes_with_support:
            _  =  support.AssignSupportToNode(node,varnSupportNo)
        
        # Create Load cases and add self weight.
        load = openstaad.Load
        load._FlagAsMethod("SetLoadActive")
        load._FlagAsMethod("CreateNewPrimaryLoad")
        load._FlagAsMethod("AddSelfWeightInXYZ")

        case_num = load.CreateNewPrimaryLoad("Self Weight")
        ret = load.SetLoadActive(case_num)  # Load Case 1
        ret = load.AddSelfWeightInXYZ(2, -1.0)  # Load factor

        # Run analysis in silent mode.
        command = openstaad.Command
        command._FlagAsMethod("PerformAnalysis")
        openstaad._FlagAsMethod("SetSilentMode")
        openstaad._FlagAsMethod("Analyze")
        openstaad._FlagAsMethod("isAnalyzing")
        command.PerformAnalysis(6)
        openstaad.SaveModel(1)
        time.sleep(3)
        openstaad.SetSilentMode(1)

        openstaad.Analyze()
        while openstaad.isAnalyzing():
            print("...Analyzing")
            time.sleep(2)

        time.sleep(5)
        
        member_y_displacement = get_members_z_displacements(openstaad=openstaad, members_dict=member_dict, case_num=case_num)
        print(member_y_displacement)
        iteration_list.append(member_y_displacement)


    # Save to JSON file
    json_path = Path.cwd() / "STAAD_output.json"
    with open(json_path, "w") as jsonfile:
        json.dump({"iterations": iteration_list}, jsonfile)

    openstaad = None
    CoUninitialize()

    # staad_process.terminate()
    return ret if ret is not None else -1

if __name__ == "__main__":
    openstaad = run_staad()