from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterable

from viktor.core import File
from viktor.external.generic import GenericAnalysis

from app.steps import step


@step("ensure_input_json")
def ensure_input_json(base_dir: Path) -> Path:
    path = base_dir / "input_staad_updated.json"
    if not path.exists():
        raise FileNotFoundError("input_staad_updated.json not found. Visit 'Modify / Visualize Sections' first.")
    return path


@step("select_original_rvt")
def select_original_rvt(base_dir: Path) -> Path:
    models: list[Path] = sorted(base_dir.glob("*.rvt"))
    if not models:
        raise FileNotFoundError("No original RVT model found. Run conversion first.")
    return models[0]


@step("read_stage_bytes")
def read_staged_files(model_path: Path, input_json_path: Path) -> tuple[bytes, bytes]:
    try:
        return model_path.read_bytes(), input_json_path.read_bytes()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Failed reading staged files: {e}")


@step("prepare_update_worker_script")
def prepare_update_worker_script(script_dir: Path) -> File:
    script_path = script_dir / "revit_worker_edit.py"
    if not script_path.exists():
        raise FileNotFoundError("Worker script revit_worker_edit.py missing")
    return File.from_path(script_path)


def _extract_bytes(obj: object) -> bytes:
    attempts: Iterable[str] = ("getvalue", "get_bytes", "read", "read_bytes")
    for name in attempts:
        func = getattr(obj, name, None)
        if callable(func):
            try:  # Try binary flags first
                try:
                    data = func(binary=True)  # type: ignore[misc]
                except TypeError:
                    try:
                        data = func(as_bytes=True)  # type: ignore[misc]
                    except TypeError:
                        data = func()
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data)
                if isinstance(data, str):
                    import base64
                    # Try base64 decode, else treat as utf-8
                    try:
                        return base64.b64decode(data, validate=True)
                    except Exception:  # noqa: BLE001
                        return data.encode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                continue
    raise ValueError("Could not obtain bytes from worker output object")


@step("run_update_worker")
def run_update_worker(
    script: File,
    model_name: str,
    model_bytes: bytes,
    input_json_bytes: bytes,
    timeout: int = 600,
) -> bytes:
    files_to_stage = [
        ("revit_worker_edit.py", script),
        (model_name, BytesIO(model_bytes)),
        ("input.json", BytesIO(input_json_bytes)),
    ]
    try:
        update_analysis = GenericAnalysis(
            executable_key="revit",
            files=files_to_stage,
            output_filenames=["updated_model.rvt"],
        )  # type: ignore[arg-type]
        update_analysis.execute(timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Update worker failed: {e}")

    try:
        updated_file = update_analysis.get_output_file("updated_model.rvt")
        if updated_file is None:
            raise RuntimeError("Worker did not produce updated_model.rvt")
        return _extract_bytes(updated_file)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Could not retrieve updated model: {e}")


@step("persist_updated_model")
def persist_updated_model(base_dir: Path, updated_bytes: bytes, filename: str = "updated_model.rvt") -> Path:
    try:
        path = base_dir / filename
        path.write_bytes(updated_bytes)
        return path
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Failed writing updated model: {e}")
