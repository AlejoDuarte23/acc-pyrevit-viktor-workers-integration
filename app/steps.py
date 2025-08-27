from typing import Callable, Optional, Any
from functools import wraps

class StepErrors:
    def __init__(self) -> None:
        self.errors: list[Exception] = []

    def reraise(self) -> None:
        if self.errors:
            raise ExceptionGroup("one or more steps failed", self.errors)

    def has_errors(self) -> bool:
        return bool(self.errors)


def step(label: str) -> Callable[[Callable[..., Any]], Callable[..., Optional[Any]]]:
    """Decorator collecting exceptions into StepErrors and returning None on failure.

    The wrapped function must be invoked with _ctx=StepErrors; the wrapped
    function itself does not receive _ctx (it's popped before call).
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Optional[Any]]:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Optional[Any]:
            ctx = kwargs.pop("_ctx", None)
            if not isinstance(ctx, StepErrors):
                raise RuntimeError(f"{fn.__name__} requires _ctx=StepErrors")
            try:
                return fn(*args, **kwargs)
            except BaseException as e:  # noqa: BLE001
                try:
                    e.add_note(f"step={label}")  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover - note add best effort
                    pass
                if isinstance(e, Exception):
                    ctx.errors.append(e)
                else:
                    ctx.errors.append(Exception(str(e)))
                return None
        return wrapped
    return decorator
