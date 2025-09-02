import subprocess
import time
import json 
import comtypes.client

from pythoncom import CoInitialize, CoUninitialize
from datetime import datetime
from pathlib import Path
from openstaad import Output

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

    # Load lines and nodes 
    # Create joints
    input_json = Path.cwd() / "STAAD_inputs.json"
    with open(input_json) as jsonfile:
        data = json.load(jsonfile)

    nodes, lines, section_name = data[:]

    # Wait to load interface
    time.sleep(10)

    # Set Material and Beam Section
    staad_property = openstaad.Property
    staad_property._FlagAsMethod("SetMaterialName")
    staad_property._FlagAsMethod("CreateBeamPropertyFromTable")
    material_name = "STEEL"
    staad_property.SetMaterialName(material_name)

    country_code = 7  # European database.
    # section_name = "IPE400"  # Selected profile.
    type_spec = 0  # ST (Single Section from Table).
    add_spec_1 = 0.0  # Not used for single sections
    add_spec_2 = 0.0  # Must be 0.0.

    # Create the beam property.
    property_no = staad_property.CreateBeamPropertyFromTable(
        country_code, section_name, type_spec, add_spec_1, add_spec_2
    )

    # Create Members.
    geometry = openstaad.Geometry
    geometry._FlagAsMethod("CreateNode")
    geometry._FlagAsMethod("CreateBeam")
    staad_property._FlagAsMethod("AssignBeamProperty")
    
    create_nodes = set()
    for line_id, vals in lines.items():
        Ni_id = str(vals["Ni"])
        Nj_id = str(vals["Nj"])
        Ni_cords = nodes[Ni_id]
        Nj_cords = nodes[Nj_id]
        if Ni_id not in create_nodes:
            geometry.CreateNode(int(Ni_id), Ni_cords["x"], Ni_cords["y"], Ni_cords["z"])
            create_nodes.add(Ni_id)
        if Nj_id not in create_nodes:
            geometry.CreateNode(int(Nj_id), Nj_cords["x"], Nj_cords["y"], Nj_cords["z"])
            create_nodes.add(Nj_id)
        geometry.CreateBeam(int(line_id), Ni_id, Nj_id)
        _ = staad_property.AssignBeamProperty(int(line_id), property_no)
    
    # Create supports.
    support = openstaad.Support
    support._FlagAsMethod("CreateSupportFixed")
    support._FlagAsMethod("AssignSupportToNode")

    varnSupportNo  = support.CreateSupportFixed()
    nodes_with_support = [1,2,5,6]
    for node in nodes_with_support:
        _  =  support.AssignSupportToNode(node,varnSupportNo)
    
    # Create Load cases and add self weight.
    load = openstaad.Load
    load._FlagAsMethod("SetLoadActive")
    load._FlagAsMethod("CreateNewPrimaryLoad")
    load._FlagAsMethod("AddSelfWeightInXYZ")

    case_num = load.CreateNewPrimaryLoad("Self Weight")
    ret = load.SetLoadActive(case_num) # Load Case 1
    ret = load.AddSelfWeightInXYZ(2, -1.0) # Load factor
    
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
    # Process Outputs.
    output = Output()
    #  GetMemberEndForces returns -> FX, FY, FZ, MX, MY and MZ (in order).
    end_forces = [list(output.GetMemberEndForces(beam=int(bid), start=False, lc=1)) for bid in lines]
    end_headers = [f"Beam:{bid}/Node:{lines[bid]['Nj']}" for bid in lines]

    start_forces = [list(output.GetMemberEndForces(beam=int(bid), start=True, lc=1)) for bid in lines]
    start_headers = [f"Beam:{bid}/Node:{lines[bid]['Ni']}" for bid in lines]

    # Combine forces and headers into lists of lists
    forces = end_forces + start_forces
    headers = end_headers + start_headers

    # Save to JSON file
    json_path = Path.cwd() / "STAAD_output.json"
    with open(json_path, "w") as jsonfile:
        json.dump({"forces": forces, "headers": headers}, jsonfile)

    openstaad = None
    CoUninitialize()

    staad_process.terminate()
    return ret

if __name__ == "__main__":
    openstaad = run_staad()