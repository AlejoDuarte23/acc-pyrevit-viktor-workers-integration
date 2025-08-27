from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Callable, Optional, Any
from functools import wraps

class StepErrors:
	def __init__(self) -> None:
		# keep a list of Exception (not BaseException) to satisfy type checkers
		self.errors: list[Exception] = []

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
				# convert BaseException to Exception for consistent storage
				if isinstance(e, Exception):
					ctx.errors.append(e)
				else:
					ctx.errors.append(Exception(str(e)))
				return None
		return wrapped
	return decorator

PYREVIT_SCRIPT = (
	r"C:\Users\aleja\AppData\Roaming\pyRevit-Master\extensions\PullAnalyticalModel.extension\PullAnalyticalModel.tab\Exports.panel\UpdateModelFeatures.pushbutton\script.py"
)

# Deterministic filename the orchestrator (PythonAnalysis) will fetch.
UPDATED_OUTPUT_NAME = "updated_model.rvt"

def debugListFiles(base: Path, label: str) -> None:
	"""Debug helper: print .rvt and .json files with size & mtime."""
	try:
		print(f"[revit_worker_edit][debug] File snapshot {label}:", flush=True)
		for pattern in ("*.rvt", "*.json"):
			for p in sorted(base.glob(pattern)):
				try:
					stat = p.stat()
					print(
						f"  - {p.name:30} {stat.st_size:9} bytes  mtime={stat.st_mtime}",
						flush=True,
					)
				except Exception as e:  # pragma: no cover - best effort
					print(f"  - {p.name} <stat error: {e}>", flush=True)
	except Exception as e:  # pragma: no cover - best effort
		print(f"[revit_worker_edit][debug] Could not list files: {e}", flush=True)


@step("find_input_json")
def findSingleInputJson(base: Path) -> Path:
	p = base / "input.json"
	if not p.exists():
		raise FileNotFoundError("input.json not found for update worker (expected staged next to script)")
	return p.resolve()


@step("find_model_file")
def findModelFile(base: Path) -> Path:
	rvts = sorted(base.glob("*.rvt"))
	if not rvts:
		raise FileNotFoundError("No .rvt file found for update worker")
	# If multiple, pick the newest (likely the staged one if unique timestamps).
	rvts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
	return rvts[0].resolve()


@step("set_env_and_snapshot")
def setEnvAndSnapshot(script_dir: Path, input_json: Path) -> dict[str, float]:
	"""Set environment variables required by the pyRevit script and snapshot RVT mtimes."""
	os.environ["REVIT_ANALYTICAL_UPDATE_JSON"] = str(input_json)
	os.environ["REVIT_ANALYTICAL_SAVEAS_PATH"] = str(script_dir)
	print("[revit_worker_edit][debug] Environment variables set:", flush=True)
	print(f"  REVIT_ANALYTICAL_UPDATE_JSON={os.environ['REVIT_ANALYTICAL_UPDATE_JSON']}", flush=True)
	print(f"  REVIT_ANALYTICAL_SAVEAS_PATH={os.environ['REVIT_ANALYTICAL_SAVEAS_PATH']}", flush=True)
	# Snapshot existing RVT mtimes
	before_snapshot = {str(p): p.stat().st_mtime for p in script_dir.glob("*.rvt")}
	return before_snapshot


@step("run_pyrevit")
def runPyrevit(script_path: str, model_path: Path) -> int:
	command = f'pyrevit run "{script_path}" "{model_path}"'
	print(f"[revit_worker_edit] Running: {command}")
	exit_code = os.system(command)
	if exit_code != 0:
		print(f"[revit_worker_edit] pyRevit command exited with code {exit_code}")
	return exit_code


@step("select_and_copy_updated")
def selectAndCopyUpdated(before_snapshot: dict[str, float], script_dir: Path) -> None:
	newest = selectNewestRvt(before_snapshot, script_dir)
	target = script_dir / UPDATED_OUTPUT_NAME
	if newest != target:
		shutil.copy2(newest, target)
		print(f"[revit_worker_edit] Copied '{newest.name}' -> '{target.name}' for orchestrator pickup")
	else:
		print(f"[revit_worker_edit] Updated model already named {UPDATED_OUTPUT_NAME}")


def selectNewestRvt(before: dict[str, float], after_dir: Path) -> Path:
	""" This is like this because I was sloppy in the revit extension: TODO: make the extension return updated.rvt"""
	candidates = list(after_dir.glob("*.rvt"))
	if not candidates:
		raise FileNotFoundError("No RVT files present after update run")
	updated = []
	for c in candidates:
		mtime = c.stat().st_mtime
		prev = before.get(str(c))
		if prev is None or mtime > prev + 1e-6:
			updated.append((mtime, c))
	if updated:
		updated.sort(reverse=True)
		return updated[0][1]
	candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
	return candidates[0]


def main() -> int:
	script_dir = Path(__file__).parent

	ctx = StepErrors()

	input_json = findSingleInputJson(script_dir, _ctx=ctx)
	model_path = findModelFile(script_dir, _ctx=ctx)

	before_snapshot = None
	if input_json is not None:
		before_snapshot = setEnvAndSnapshot(script_dir, input_json, _ctx=ctx)

	debugListFiles(script_dir, "before run")

	exit_code = 0
	if model_path is not None:
		res = runPyrevit(PYREVIT_SCRIPT, model_path, _ctx=ctx)
		if isinstance(res, int):
			exit_code = res

	debugListFiles(script_dir, "after run")

	# Attempt to select & copy updated model even if pyRevit returned non-zero
	if before_snapshot is not None:
		selectAndCopyUpdated(before_snapshot, script_dir, _ctx=ctx)

	# Raise one group if any step failed
	ctx.reraise()
	print("[revit_worker_edit] Completed without collected errors")
	return exit_code


if __name__ == "__main__":
	raise SystemExit(main())


