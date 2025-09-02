import viktor as vkt
import requests
import base64
import json
import app.aps_helpers as aps_helpers
from io import BytesIO
from app.plots import model_viz
from app.conver_revit_model import (
    pull_revit_file_from_acc,
    run_revit_worker,
    parse_revit_model,
)
from app.steps import StepErrors
from app.modify_model_in_viktor import (
    load_output_json,
    prepare_working_copy,
    apply_section_override,
    write_input_json,
)
from app.update_revit_model import (
    ensure_input_json,
    select_original_rvt,
    read_staged_files,
    prepare_update_worker_script,
    run_update_worker,
    persist_updated_model,
)
from pathlib import Path
from viktor.core import File
from viktor.external.python import PythonAnalysis

class APSView(vkt.WebView):
    pass

def get_view_options(params, **kwargs):
    """Return OptionListElements for 3D/2D views of the currently selected viewable.

    After modification of get_viewable_files_names, params.viewable_file now directly
    stores the URN (value of the selected option). We therefore skip the lookup dict.
    """
    # Adjusted for Step structure: fields now under params.step1
    if not params.step1.viewable_file:
        return ["Select a viewable file first"]    

    urn = params.step1.viewable_file  # already the URN

    integration = vkt.external.OAuth2Integration("aps-integration-viktor")
    token = integration.get_access_token()
    
    encoded_urn = base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")
    url = f"https://developer.api.autodesk.com/modelderivative/v2/designdata/{encoded_urn}/manifest"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        manifest = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching manifest: {e}")
        return ["Error fetching manifest"]

    options = []
    # Find the main derivative with viewable geometry
    for derivative in manifest.get("derivatives", []):
        if derivative.get("outputType") in ["svf", "svf2"]:
            # Find the parent geometry nodes for both 3D and 2D
            for geometry_node in derivative.get("children", []):
                
                if geometry_node.get("type") == "geometry" and geometry_node.get("role") in ["3d", "2d"]:
                    view_name = geometry_node.get("name")
                    view_guid = None
                    view_role = geometry_node.get("role") # '3d' or '2d'

                    # Search its children for the actual node with "type": "view"
                    for child_node in geometry_node.get("children", []):
                        if child_node.get("type") == "view":
                            view_guid = child_node.get("guid")
                            if child_node.get("name").startswith("Sheet:"):
                                view_name = child_node.get("name")
                            break # Found the correct view node
                    
                    if view_name and view_guid:
                        # I added this prefix but can be ommited
                        label_prefix = "[3D]" if view_role == "3d" else "[2D]"
                        options.append(vkt.OptionListElement(label=f"{label_prefix} {view_name}", value=view_guid))

    if not options:
        return ["No 3D or 2D views found in manifest"]
    
    
    return options

@vkt.memoize
def get_viewable_files_dict(params, **kwargs) -> dict[str, dict[str, str]]:
    """ Return a dictionary with keys -> file name, and vals as a dict of file name and urn"""
    integration = vkt.external.OAuth2Integration("aps-integration-viktor")
    token = integration.get_access_token()
    if not params.step1.hubs:
        # Return an empty dict to avoid NoneType issues upstream
        return {}
    hub_id = aps_helpers.get_hub_id_by_name(token, params.step1.hubs)
    viewable_dict = aps_helpers.get_all_cad_file_from_hub(token=token, hub_id=hub_id) or {}
    return viewable_dict


def get_hub_list(params, **kwargs) -> list[str]:
    integration = vkt.external.OAuth2Integration("aps-integration-viktor")
    token = integration.get_access_token()
    hub_names = aps_helpers.get_hub_names(token)
    return hub_names if hub_names else ["No hubs found"]

def get_viewable_files_names(params, **kwargs):
    """Return list of OptionListElement where value is the file URN.

    Mirrors style of get_view_options so downstream logic can use params.viewable_file
    directly as a URN.
    """
    if not params.step1.hubs:
        return ["Select a hub first!"]
    viewable_file_dict = get_viewable_files_dict(params, **kwargs)
    if not viewable_file_dict:
        return [vkt.OptionListElement(label="No viewable files in the hub", value="")]
    options = []
    for name, meta in viewable_file_dict.items():
        urn = meta.get("urn")
        if urn:
            options.append(vkt.OptionListElement(label=name, value=urn))
    if not options:
        return [vkt.OptionListElement(label="No viewable files in the hub", value="")]
    return options


class Parametrization(vkt.Parametrization):
    step1 = vkt.Step("ACC Model Selection", views=["viewer_page"])
    step1.title = vkt.Text("# Model Selection - ACC - Viktor Integration")
    step1.br1 = vkt.LineBreak()
    step1.hubs = vkt.OptionField("Avaliable Hubs", options=get_hub_list)
    step1.br2 = vkt.LineBreak()
    step1.viewable_file = vkt.OptionField("Available Viewables", options=get_viewable_files_names)
    step1.br3 = vkt.LineBreak()
    step1.select_view = vkt.OptionField("Select View", options=get_view_options)
    step1.br4 = vkt.LineBreak()

    step2 = vkt.Step("Process Revit Model - Viktor Worker", views= ["convert_model"])
    step2.title = vkt.Text("# Visualize Structural Elements in Plotly")
    step2.description = vkt.Text("Reload the PlotlyView to run the worker and visualize the parsed revit model in the view!")

    step3 = vkt.Step("Modify Model in Viktor and Update Revit Model!", views=["modify_model_in_viktor"])
    step3.text = vkt.Text("Modify Revit Model")
    step3.sections = vkt.OptionField("Select Cross Sections", options=["UB406x178x60", "UB254x102x28", "Original Sections"], default="Original Sections")
    step3.br33 = vkt.LineBreak()
    step3.buttom = vkt.DownloadButton("Update Revit Model", method="update_revit_model")
    step3.staad_buttom = vkt.DownloadButton("Create STAAD Model", method="run_staad_model")

class Controller(vkt.Controller):
    parametrization = Parametrization(width=40)

    @vkt.WebView("APS Viewer", duration_guess=5)
    def viewer_page(self, params, **kwargs):
        """WebView that loads the APS Viewer with the selected view GUID."""
        selected_guid = params.step1.select_view
        print(selected_guid)
        integration = vkt.external.OAuth2Integration("aps-integration-viktor")
        token = integration.get_access_token()
        # params.viewable_file now contains the URN directly
        urn = params.step1.viewable_file
        if not urn:
            return vkt.WebResult(html="<p>No URN selected.</p>")
        try:
            file_meta = None
            file_name = None
            all_files = get_viewable_files_dict(params)
            for name, meta in all_files.items():
                if meta.get("urn") == urn:
                    file_meta = meta
                    file_name = name
                    break
            if file_meta and file_name:
                project_id = file_meta.get("project_id")
                item_id = file_meta.get("item_id")
                if project_id and item_id:
                    try:
                        raw_bytes = aps_helpers.get_file_content(token, project_id, item_id)
                        # Persist locally under downloaded_files/<file_name>
                        safe_name = file_name.replace("/", "_").replace("\\", "_")
                        output_dir = Path(__file__).parent / "downloaded_files"
                        output_dir.mkdir(exist_ok=True)
                        out_path = output_dir / safe_name
                        out_path.write_bytes(raw_bytes)
                        print(
                            f"Saved file '{safe_name}' ({len(raw_bytes)} bytes) to {out_path} (project={project_id}, item={item_id})"
                        )
                    except Exception as e:
                        print(f"Failed to fetch file content: {e}")
        except Exception as e:
            print(f"Metadata lookup failed: {e}")

        encoded_urn = base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")

        html = (Path(__file__).parent / "ViewableViewer.html").read_text()
        html = html.replace("APS_TOKEN_PLACEHOLDER", token)
        html = html.replace("URN_PLACEHOLDER", encoded_urn) # Pass the ENCODED urn
        html = html.replace("VIEW_GUID_PLACEHOLDER", selected_guid or "")
        return vkt.WebResult(html=html)
    
    @vkt.PlotlyView(label="RVT2VKT!", duration_guess=40)
    def convert_model(self, params, **kwargs) -> vkt.PlotlyResult:
        # Download the selected file (if not already) and pass it to the worker.
        integration = vkt.external.OAuth2Integration("aps-integration-viktor")
        token = integration.get_access_token()

        urn = params.step1.viewable_file
        if not urn:
            print("convert_model: No URN selected")
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())

        errors = StepErrors()

        viewable_dict = get_viewable_files_dict(params)

        res = pull_revit_file_from_acc(token, urn, viewable_dict, _ctx=errors)
        if res is None:
            errors.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())
        safe_name, raw_bytes = res

        output_json = run_revit_worker(safe_name, raw_bytes, _ctx=errors)
        if output_json is None:
            errors.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())

        parsed = parse_revit_model(output_json, _ctx=errors)
        if parsed is None:
            errors.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())

        nodes, lines, cross_sections, members = parsed

        try:
            fig = model_viz.plot_3d_model(nodes, lines, members, cross_sections)
        except Exception as e:
            print(f"convert_model: Failed to build figure: {e}")
            fig = model_viz.default_blank_scene()
        # If any steps collected errors, raise them now
        try:
            errors.reraise()
        except Exception as e:
            print(f"convert_model: completed with collected errors: {e}")
        return vkt.PlotlyResult(figure=fig)

    @vkt.PlotlyView(label="Modify / Visualize Sections", duration_guess=20)
    def modify_model_in_viktor(self, params, **kwargs) -> vkt.PlotlyResult:
        selection = getattr(getattr(params, "step3", object()), "sections", None)
        base_dir = Path(__file__).parent / "downloaded_files"
        ctx = StepErrors()

        data = load_output_json(base_dir, _ctx=ctx)
        if data is None:
            ctx.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())

        working = prepare_working_copy(data, _ctx=ctx) or data

        working, modified = apply_section_override(working, selection, _ctx=ctx) or (working, 0)
        if modified:
            print(f"modify_model: applied section override '{selection}' to {modified} members (in-memory)")
        else:
            print("modify_model: using original sections (no override)")

        written = write_input_json(base_dir, working, _ctx=ctx)
        if written is not None:
            print("modify_model: input.json written")

        parsed = parse_revit_model(working, _ctx=ctx)
        if parsed is None:
            ctx.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())
        nodes, lines, cross_sections, members = parsed

        try:
            fig = model_viz.plot_3d_model(nodes, lines, members, cross_sections)
        except Exception as e:  # noqa: BLE001
            print(f"modify_model: plotting failed: {e}")
            fig = model_viz.default_blank_scene()

        try:
            ctx.reraise()
        except Exception as e:  # noqa: BLE001
            print(f"modify_model: completed with collected errors: {e}")
        return vkt.PlotlyResult(figure=fig)

    def update_revit_model(self, params, **kwargs):
        base_dir = Path(__file__).parent / "downloaded_files"
        ctx = StepErrors()

        input_json_path = ensure_input_json(base_dir, _ctx=ctx)
        if input_json_path is None:
            ctx.reraise()
            return None

        model_path = select_original_rvt(base_dir, _ctx=ctx)
        if model_path is None:
            ctx.reraise()
            return None

        staged = read_staged_files(model_path, input_json_path, _ctx=ctx)
        if staged is None:
            ctx.reraise()
            return None
        model_bytes, input_json_bytes = staged

        script = prepare_update_worker_script(Path(__file__).parent, _ctx=ctx)
        if script is None:
            ctx.reraise()
            return None

        updated_bytes = run_update_worker(
            script,
            model_path.name,
            model_bytes,
            input_json_bytes,
            _ctx=ctx,
        )
        if updated_bytes is None:
            ctx.reraise()
            return None

        persisted = persist_updated_model(base_dir, updated_bytes, _ctx=ctx)
        if persisted is None:
            ctx.reraise()
            return None

        try:
            ctx.reraise()
        except Exception as e:
            print(f"update_revit_model: completed with collected errors: {e}")
        return vkt.DownloadResult(updated_bytes, file_name="updated_revit_model.rvt")
    

    def run_staad_model(self, params, **kwargs) -> vkt.DownloadResult | None:
        script_path = Path(__file__).parent / "run_staad_model.py"
        input_json_path = Path(__file__).parent / "downloaded_files" / "output.json"

        if not script_path.exists():
            raise FileNotFoundError("Worker script revit_worker.py missing")
        
        if not input_json_path.exists():
            raise FileNotFoundError("output.json missing")
        
        with open(input_json_path, encoding="utf-8") as jsonfile:
            input_data = json.load(jsonfile)

        # Build context for step-decorated parse function
        ctx = StepErrors()
        parsed = parse_revit_model(output_json=input_data, _ctx=ctx)
        if parsed is None:
            ctx.reraise()
            return None
        nodes, lines, cross_sections, members = parsed

        # Decide section name: user selection if not 'Original', else first cross section name or fallback
        selection = getattr(getattr(params, "step3", object()), "sections", None)
        if selection and selection != "Original Sections":
            section_name = selection
        else:
            try:
                first_cs = next(iter(cross_sections.values()))
                section_name = first_cs["name"]
            except Exception:
                section_name = "IPE400"  # conservative fallback

        staad_input = json.dumps([nodes, lines, section_name])
        script = File.from_path(script_path)

        model_files = [("STAAD_inputs.json", BytesIO(staad_input.encode("utf-8")))]

        analysis = PythonAnalysis(script=script, files=model_files, output_filenames=["STAAD_output.json"])  # type: ignore[arg-type]
        analysis.execute(timeout=300)

        output_file_obj = analysis.get_output_file("STAAD_output.json")
        if output_file_obj is None:
            raise RuntimeError("STAAD worker did not produce STAAD_output.json")

        # Extract bytes from output file object
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
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    continue
            if contents is not None:
                break
        if isinstance(contents, str):
            contents_bytes = contents.encode("utf-8")
        elif isinstance(contents, (bytes, bytearray)):
            contents_bytes = bytes(contents)
        else:
            raise RuntimeError("Unable to read STAAD_output.json content")

        try:
            ctx.reraise()
        except Exception as e:  # noqa: BLE001
            print(f"run_staad_model: completed with collected errors: {e}")
        return vkt.DownloadResult(contents_bytes, file_name="STAAD_output.json")
