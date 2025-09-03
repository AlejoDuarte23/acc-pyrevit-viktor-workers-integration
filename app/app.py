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
from app.opensees.connecte_intersetc_lines import connect_lines_at_intersections
from pathlib import Path
from viktor.core import File
from viktor.external.python import PythonAnalysis
import textwrap


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
                if geometry_node.get("type") == "geometry" and geometry_node.get(
                    "role"
                ) in ["3d", "2d"]:
                    view_name = geometry_node.get("name")
                    view_guid = None
                    view_role = geometry_node.get("role")  # '3d' or '2d'

                    # Search its children for the actual node with "type": "view"
                    for child_node in geometry_node.get("children", []):
                        if child_node.get("type") == "view":
                            view_guid = child_node.get("guid")
                            if child_node.get("name").startswith("Sheet:"):
                                view_name = child_node.get("name")
                            break  # Found the correct view node

                    if view_name and view_guid:
                        # I added this prefix but can be ommited
                        label_prefix = "[3D]" if view_role == "3d" else "[2D]"
                        options.append(
                            vkt.OptionListElement(
                                label=f"{label_prefix} {view_name}", value=view_guid
                            )
                        )

    if not options:
        return ["No 3D or 2D views found in manifest"]

    return options


def get_viewable_files_dict(params, **kwargs) -> dict[str, dict[str, str]]:
    """Return a dictionary with keys -> file name, and vals as a dict of file name and urn"""
    integration = vkt.external.OAuth2Integration("aps-integration-viktor")
    token = integration.get_access_token()
    if not params.step1.hubs:
        # Return an empty dict to avoid NoneType issues upstream
        return {}
    hub_id = aps_helpers.get_hub_id_by_name(token, params.step1.hubs)
    viewable_dict = (
        aps_helpers.get_all_cad_file_from_hub(token=token, hub_id=hub_id) or {}
    )
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
    step1.viewable_file = vkt.OptionField(
        "Available Viewables", options=get_viewable_files_names
    )
    step1.br3 = vkt.LineBreak()
    step1.select_view = vkt.OptionField("Select View", options=get_view_options)
    step1.br4 = vkt.LineBreak()

    step2 = vkt.Step("Process Revit Model - Viktor Worker", views=["convert_model"])
    step2.title = vkt.Text("# Visualize Structural Elements in Plotly")
    step2.description = vkt.Text(
        "Reload the PlotlyView to run the worker and visualize the parsed revit model in the view!"
    )

    step3 = vkt.Step(
        "Modify Model in Viktor and Update Revit Model!",
        views=["modify_model_in_viktor"],
    )
    # step3.text1 = vkt.Text("# Modify Revit Model")
    # step3.sections = vkt.OptionField("Select Cross Sections", options=["UB406x178x60", "UB254x102x28", "Original Sections"], default="Original Sections")
    step3.text2 = vkt.Text(
        textwrap.dedent(
            """
            ## Analysis Settings
            Assign point load in all the nodes for the model. The self weight of the structure will be add it atumatiaclly in STAAAD.PRO. The model will select the optimal section to comply with the allowable deformation asigned to the analysis
            """
        )
    )
    step3.load_mag = vkt.NumberField("Load Magnitud [kN]", default=1)
    step3.br55 = vkt.LineBreak()
    step3.allowable_deformation = vkt.NumberField(
        "Allowable Deformation [mm]", default=10
    )
    step3.br66 = vkt.LineBreak()
    step3.text3 = vkt.Text(
        textwrap.dedent(
            """
            ## Run STAAD
            Create a STAAD.Pro model using the loads and run a serviceability assessment to optimize the model to comply with the allowable displacements
            """
        )
    )
    step3.staad_buttom = vkt.ActionButton(
        "Create STAAD Model", method="run_staad_model"
    )
    step3.br77 = vkt.LineBreak()
    step3.boolean = vkt.BooleanField("Toggle to Update Result!")
    step3.text4= vkt.Text(
        textwrap.dedent(
            """
            ## Update Revit Model
            Sync the STAAD.PRO model with revit model, and allow you to download it for revision!
            """
        )
    )
    step3.buttom = vkt.DownloadButton("Update Revit Model", method="update_revit_model")


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
                        raw_bytes = aps_helpers.get_file_content(
                            token, project_id, item_id
                        )
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
        html = html.replace("URN_PLACEHOLDER", encoded_urn)  # Pass the ENCODED urn
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
        use_staad = getattr(getattr(params, "step3", object()), "boolean", False)
        base_dir = Path(__file__).parent / "downloaded_files"
        ctx = StepErrors()

        # Select file based on boolean
        if use_staad:
            json_path = base_dir / "input_staad_updated.json"
        else:
            json_path = base_dir / "output.json"

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"modify_model: failed to read {json_path.name}: {e}")
            ctx.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())

        working = prepare_working_copy(data, _ctx=ctx) or data
        working, modified = apply_section_override(working, selection, _ctx=ctx) or (working, 0)
        if modified:
            print(f"modify_model: applied section override '{selection}' to {modified} members (in-memory)")
        else:
            print("modify_model: using original sections (no override)")

        parsed = parse_revit_model(working, _ctx=ctx)
        if parsed is None:
            ctx.reraise()
            return vkt.PlotlyResult(figure=model_viz.default_blank_scene())
        nodes, lines, cross_sections, members = parsed

        try:
            fig = model_viz.plot_3d_model(nodes, lines, members, cross_sections)
        except Exception as e:
            print(f"modify_model: plotting failed: {e}")
            fig = model_viz.default_blank_scene()

        try:
            ctx.reraise()
        except Exception as e:
            print(f"modify_model: completed with collected errors: {e}")
        return vkt.PlotlyResult(figure=fig)

    def update_revit_model(self, params, **kwargs):
        """This looks for input.json in the downloaded_files folder"""
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

        # Parse model
        ctx = StepErrors()
        parsed = parse_revit_model(output_json=input_data, _ctx=ctx)
        if parsed is None:
            ctx.reraise()
            return None
        nodes, lines, cross_sections, members = parsed

        # Build connectivity with augmented child mapping
        nodes2, lines2, members2, mother_to_children, child_to_mother = connect_lines_at_intersections(
            nodes, lines, members, tol=1e-4
        )

        # Decide section override to send to worker
        selection = getattr(getattr(params, "step3", object()), "sections", None)
        if selection and selection != "Original Sections":
            section_override = selection
        elif selection == "Original Sections":
            section_override = "Original Sections"
        else:
            try:
                first_cs = next(iter(cross_sections.values()))
                section_override = first_cs["name"]
            except Exception:
                section_override = "IPE400"

        # Package input for worker
        staad_input = json.dumps(
            [
                nodes2,
                lines2,
                section_override,
                members2,
                cross_sections,
                params.step3.allowable_deformation,
                params.step3.load_mag,
            ]
        )
        dl_dir = Path(__file__).parent / "downloaded_files"
        dl_dir.mkdir(exist_ok=True)
        staad_input_path = dl_dir / "STAAD_inputs.json"
        try:
            staad_input_path.write_text(staad_input, encoding="utf-8")
        except Exception as e:
            print(f"Failed to write STAAD_inputs.json locally: {e}")

        script = File.from_path(script_path)
        model_files = [("STAAD_inputs.json", BytesIO(staad_input.encode("utf-8")))]
        analysis = PythonAnalysis(script=script, files=model_files, output_filenames=["STAAD_output.json"])  # type: ignore[arg-type]
        analysis.execute(timeout=300)

        output_file_obj = analysis.get_output_file("STAAD_output.json")
        if output_file_obj is None:
            raise RuntimeError("STAAD worker did not produce STAAD_output.json")

        contents = json.loads(output_file_obj.getvalue())
        updated_member_dict, updated_cs_dict = contents

        # Load original input.json to update
        base_dir = Path(__file__).parent / "downloaded_files"
        input_json_path2 = base_dir / "input.json"
        if not input_json_path2.exists():
            raise FileNotFoundError("input.json not found for update after STAAD run")
        working_data = json.loads(input_json_path2.read_text(encoding="utf-8"))

        # Helper to parse last number in a section name
        def get_last_number(section_name: str) -> float:
            try:
                import re
                parts = section_name.split("x")
                if len(parts) > 1:
                    try:
                        return float(parts[-1])
                    except Exception:
                        pass
                nums = re.findall(r"\d+(?:\.\d+)?", section_name)
                if nums:
                    return max(float(n) for n in nums)
                return -1.0
            except Exception:
                return -1.0

        # Lookups from worker
        cs_info_by_id: dict[int, dict] = {}
        for k, v in updated_cs_dict.items():
            try:
                cs_info_by_id[int(k)] = v
            except Exception:
                continue

        # Map worker members by line_id for fast access
        worker_by_line: dict[int, dict] = {}
        for _, wm in updated_member_dict.items():
            try:
                worker_by_line[int(wm["line_id"])] = wm
            except Exception:
                continue

        # Members list in the original JSON
        members_iterable = working_data.get("analytical_members") or working_data.get("members") or []

        # Dual index: by line_id and by id (both are used in user exports)
        by_line: dict[int, dict] = {}
        by_id: dict[int, dict] = {}
        for m in members_iterable:
            li = m.get("line_id", None)
            if li is not None:
                try:
                    by_line[int(li)] = m
                except Exception:
                    pass
            mid = m.get("id", None)
            if mid is not None:
                try:
                    by_id[int(mid)] = m
                except Exception:
                    pass

        def get_member_from_working(line_id: int) -> dict | None:
            m = by_line.get(line_id)
            if m is not None:
                return m
            # Some files use "id" equal to the analytical line id
            return by_id.get(line_id)

        # 1) Apply worker sections to all child members present in the working JSON
        applied_children = 0
        for _, wm in updated_member_dict.items():
            try:
                line_id = int(wm["line_id"])
                cs_id = int(wm["cross_section_id"])
            except Exception:
                continue
            cs_info = cs_info_by_id.get(cs_id)
            if not cs_info:
                continue
            m = get_member_from_working(line_id)
            if m is None:
                continue
            section = m.get("section")
            if section is None:
                section = {}
                m["section"] = section
            section["type_name"] = cs_info.get("name", "Section")
            section["type_id"] = cs_info.get("id", cs_id)
            section["family_name"] = cs_info.get("name", "Section")
            m["section_properties"] = {k: v for k, v in cs_info.items() if k not in ("id", "name")}
            applied_children += 1

        # 2) For each mother, pick the governing child DIRECTLY from worker output,
        #    then write that section into the mother member in working_data.
        updated_mothers = 0
        for mother_id, child_ids in mother_to_children.items():
            best_val = None
            best_cs: dict | None = None

            for cid in child_ids:
                wm = worker_by_line.get(int(cid))
                if wm is None:
                    continue
                try:
                    cs_id = int(wm["cross_section_id"])
                except Exception:
                    continue
                cs = cs_info_by_id.get(cs_id)
                if not cs:
                    continue
                name = str(cs.get("name", ""))
                val = get_last_number(name)
                if best_val is None or val > best_val:
                    best_val = val
                    best_cs = cs

            if best_cs is None:
                continue

            mother_member = get_member_from_working(int(mother_id))
            if mother_member is None:
                continue

            before_name = mother_member.get("section", {}).get("type_name") if mother_member.get("section") else None
            mother_section = mother_member.get("section")
            if mother_section is None:
                mother_section = {}
                mother_member["section"] = mother_section

            mother_section["type_name"] = best_cs.get("name", "Section")
            mother_section["type_id"] = best_cs.get("id")
            mother_section["family_name"] = best_cs.get("name", "Section")
            mother_member["section_properties"] = {k: v for k, v in best_cs.items() if k not in ("id", "name")}
            after_name = mother_section.get("type_name")
            print(f"Mother member {mother_id}: section name before='{before_name}', after='{after_name}'")
            updated_mothers += 1

        base_dir = Path(__file__).parent / "downloaded_files"
        input_json_staad = base_dir / "input_staad_updated.json"

        # Write back
        input_json_staad.write_text(json.dumps(working_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"run_staad_model: updated {applied_children} children from worker output, "
            f"updated {updated_mothers} mothers from governing child. input.json written."
        )

        # Optional short debug: show any mothers with zero matched children in worker output
        missing = [mid for mid, kids in mother_to_children.items() if not any(k in worker_by_line for k in kids)]
        if missing:
            print(f"[DEBUG] Mothers with no children found in worker output (count={len(missing)}): {missing[:12]}")

        return None