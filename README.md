## App Workflow (Controller Logic)

1. Select Model (Step 1)
  - Pick a Hub, then a Revit file (URN) and an optional 2D/3D view.
  - The viewer loads the selected view.
  - The original RVT is downloaded once to `app/downloaded_files/`.

2. Convert Model (Step 2 – Plotly view "RVT2VKT!")
  - Steps: pull_revit_file_from_acc -> run_revit_worker -> parse_revit_model.
  - Runs the worker (`revit_worker.py`) to produce `output.json` (analytical members).
  - Parses members into nodes / lines / cross sections / members and renders a 3D Plotly scene.
  - Errors are collected (not crashing early) via `StepErrors`.

3. Modify Model (Step 3 – Plotly view "Modify / Visualize Sections")
  - Loads `output.json`.
  - Optionally overrides every member's section type with the selected option (or keeps original).
  - Always writes `input.json` (original or modified) next to `output.json`.
  - Re-parses and re-plots the model for instant feedback.

4. Update Revit Model (Download button in Step 3)
  - Ensures `input.json` and original RVT exist.
  - Runs the update worker (`revit_worker_edit.py`) with both files.
  - Receives `updated_model.rvt`, saves it, returns it as a download.


### Helper Files
| File | Purpose |
|------|---------|
| `app.py` | Controller + views orchestration |
| `conver_revit_model.py` | Pull, run worker, parse analytical model |
| `modify_model_in_viktor.py` | Load/clone/override/write Worker's outputed JSON for modifications |
| `update_revit_model.py` | Run update worker to modify the Revit File |
| `steps.py` | `step` decorator + `StepErrors` for debuging without a lot of try and catchs! |
| `downloaded_files/` | Staged RVT, `output.json`, `input.json`, `updated_model.rvt` |

## `revit_worker_edit.py`

  * Reads a companion `input.json` (staged by the orchestrator) containing
	updated section assignments or other modifications.
  * Sets environment variables so the invoked pyRevit script knows where the
	model file and JSON live and where to drop its updated model.
  * Runs the pyRevit UpdateModelFeatures script.
  * Copies the newest/modified RVT after execution to a deterministic
	filename `updated_model.rvt` that the orchestrator requested as output.

Expected staged files (placed by PythonAnalysis next to this script):
  - <original_model>.rvt (exact name opaque to us, we just discover it)
  - input.json (update instructions)

Environment variables defined for downstream pyRevit script (conventions you
can change in the pyRevit script if desired):
  REVIT_ANALYTICAL_UPDATE_JSON : absolute path to input.json
  REVIT_ANALYTICAL_OUT         : folder where updated model should be written

If the pyRevit script overwrites the model file in-place, this worker will
still detect the newest mtime and copy it to `updated_model.rvt`.
If it writes a new file, that file (with the newest mtime) is used.


## `revit_worker.py`

  * Discovers the local .rvt model file placed next to the script by the orchestrator.
  * Sets environment variables so the invoked pyRevit script knows where to drop its analytical export outputs.
  * Runs the pyRevit ExportAnalytical script to extract analytical data from the model.
  * Processes the generated JSON outputs, validates them, and creates a unified `output.json` file.
  * Writes a pointer file `latest_analytical_json.txt` pointing to the first JSON output.

Expected staged files (placed by PythonAnalysis next to this script):
  - <original_model>.rvt (exact name opaque to us, we just discover it)

Environment variables defined for downstream pyRevit script (conventions you
can change in the pyRevit script if desired):
  REVIT_ANALYTICAL_OUT : folder where analytical export outputs should be written

The script produces:
  - `output.json`: A normalized copy of the first JSON output, with pretty formatting or wrapped if invalid.
  - `latest_analytical_json.txt`: Pointer to the original JSON file.

If no JSON outputs are found, it logs a warning.