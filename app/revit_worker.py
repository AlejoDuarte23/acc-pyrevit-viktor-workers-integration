import os
import subprocess
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Callable, Optional, Any
from functools import wraps


PYREVIT_SCRIPT: Path = Path(os.environ["APPDATA"]) / "pyRevit-Master" / "extensions" / "PullAnalyticalModel.extension" / "PullAnalyticalModel.tab" / "Exports.panel" / "ExportAnalytical.pushbutton" / "script.py"
OUTPUT_FOLDER = Path(__file__).parent

class StepErrors:
    def __init__(self) -> None:
        self.errors: list[BaseException] = []

    def reraise(self) -> None:
        if self.errors:
            raise ExceptionGroup("one or more steps failed", self.errors)


def step(label: str) -> Callable[[Callable[..., Any]], Callable[..., Optional[Any]]]:
    """Decorator that collects exceptions into ctx.errors and returns None on failure.

    The wrapped function must be called with keyword argument _ctx=StepErrors.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Optional[Any]]:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Optional[Any]:
            ctx = kwargs.pop("_ctx", None)
            if not isinstance(ctx, StepErrors):
                raise RuntimeError(f"{fn.__name__} requires _ctx=StepErrors")
            try:
                return fn(*args, **kwargs)
            except BaseException as e:
                try:
                    e.add_note(f"step={label}")
                except Exception:
                    pass
                ctx.errors.append(e)
                return None
        return wrapped
    return decorator


@step("find_local_rvt")
def find_local_rvt() -> Path:
    """Return the first *.rvt file that sits in the same directory as this worker."""
    script_dir = Path(__file__).parent
    rvts = list(script_dir.glob("*.rvt"))
    if not rvts:
        raise FileNotFoundError(f"No .rvt file found in {script_dir}")
    return rvts[0].resolve()


@step("ensure_output_dir")
def ensure_output_dir(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)


@step("set_out_env")
def set_out_env(folder: Path) -> None:
    """The way of telling pyreivt where to place the output json"""
    os.environ["REVIT_ANALYTICAL_OUT"] = str(folder.resolve())


@step("run_pyrevit")
def run_pyrevit(script_path: str, model_path: Path) -> None:
    """Run the pyRevit command that produces JSON outputs."""
    cmd = ["pyrevit", "run", script_path, str(model_path)]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr)


@step("find_latest_json")
def find_latest_json(folder: Path) -> Path:
    """Pick the most recent JSON file in the output folder.
    This file is the output of the Revit extension"""
    jsons = [p for p in folder.glob("*.json") if p.is_file()]
    if not jsons:
        raise FileNotFoundError(f"No JSON outputs in {folder}")
    latest = max(jsons, key=lambda p: p.stat().st_mtime)
    return latest


@step("write_pointer_file")
def write_pointer_file(folder: Path, target: Path) -> None:
    pointer_file = folder / "latest_analytical_json.txt"
    pointer_file.write_text(str(target), encoding="utf-8")


@step("write_normalized_output")
def write_normalized_output(folder: Path, source: Path) -> None:
    """Write output.json with parsed JSON, raise JSONDecodeError on invalid data."""
    output_json_path = folder / "output.json"
    data = source.read_text(encoding="utf-8", errors="ignore")
    parsed = json.loads(data)  # may raise JSONDecodeError
    output_json_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[revit_worker] Wrote normalized JSON copy to {output_json_path}")



def main() -> int:
    ctx = StepErrors()

    model_path = find_local_rvt(_ctx=ctx)
    out_dir = OUTPUT_FOLDER.resolve()
    ensure_output_dir(out_dir, _ctx=ctx)
    set_out_env(out_dir, _ctx=ctx)

    if model_path is not None:
        run_pyrevit(PYREVIT_SCRIPT, model_path, _ctx=ctx)

    latest_json: Optional[Path] = find_latest_json(out_dir, _ctx=ctx)

    if latest_json is not None:
        write_pointer_file(out_dir, latest_json, _ctx=ctx)
        write_normalized_output(out_dir, latest_json, _ctx=ctx)

    # Raise one group if any step failed
    ctx.reraise()
    print("[revit_worker] Completed without collected errors")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except* FileNotFoundError as group:
        for e in group.exceptions:
            print(f"[revit_worker] Missing file, {e}")
        raise SystemExit(1)
    except* JSONDecodeError as group:
        for e in group.exceptions:
            print(f"[revit_worker] Invalid JSON, {e}")
        raise SystemExit(1)
    except* Exception as group:
        for e in group.exceptions:
            print(f"[revit_worker] Unhandled error, {e}")
        raise SystemExit(1)
