import json
from pathlib import Path
from typing import Tuple

from app.steps import step
# parse_revit_model is used from caller after pipeline; not imported here to avoid unused warnings.


@step("load_output_json")
def load_output_json(base_dir: Path) -> dict:
    path = base_dir / "output.json"
    if not path.exists():
        raise FileNotFoundError("output.json not found. Run conversion first.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"failed reading output.json: {e}")


@step("prepare_working_copy")
def prepare_working_copy(data: dict) -> dict:
    try:
        return json.loads(json.dumps(data))  # deep copy via serialize round-trip
    except Exception:
        # Fall back to original (caller may treat as no-modification scenario)
        return data


@step("apply_section_override")
def apply_section_override(data: dict, selection: str | None) -> Tuple[dict, int]:
    if not (selection and selection not in ("Original Sections", "")):
        return data, 0
    members_iterable = data.get("analytical_members") or data.get("members") or []
    modified = 0
    for member in members_iterable:
        try:
            section = member.get("section")
            if section is None:
                section = {}
                member["section"] = section
            section["type_name"] = selection
            modified += 1
        except Exception:
            continue
    return data, modified


@step("write_input_json")
def write_input_json(base_dir: Path, working_data: dict) -> Path:
    path = base_dir / "input.json"
    base_dir.mkdir(exist_ok=True)
    path.write_text(json.dumps(working_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path