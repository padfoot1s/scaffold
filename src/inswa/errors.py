"""Turn low-level exceptions (often nested in ExceptionGroups) into short, actionable messages."""

from __future__ import annotations


def root_cause(ex: BaseException) -> BaseException:
    """Innermost exception of an ExceptionGroup / __cause__ chain."""
    while True:
        if isinstance(ex, BaseExceptionGroup) and ex.exceptions:
            ex = ex.exceptions[0]
        elif ex.__cause__ is not None:
            ex = ex.__cause__
        else:
            return ex


def _class_names(ex: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(ex).__mro__}


def is_connection_error(ex: BaseException) -> bool:
    leaf = root_cause(ex)
    return isinstance(leaf, ConnectionError) or bool(
        _class_names(leaf) & {"ConnectError", "ConnectTimeout", "ConnectionRefusedError"}
    )


def http_status(ex: BaseException) -> int | None:
    status = getattr(getattr(root_cause(ex), "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def describe_tool_failure(ex: BaseException, timeout_seconds: float) -> str:
    """Why a specialist could not use its tools, phrased for the end user (no internal addresses)."""
    if isinstance(ex, TimeoutError):
        return f"timed out after {timeout_seconds:g}s"
    if is_connection_error(ex):
        return "could not reach the MCP tool server"
    status = http_status(ex)
    if status in (401, 403):
        return f"was refused by the MCP tool server (HTTP {status}); check MCP__AUTH / MCP__SCOPE and access"
    if status:
        return f"got HTTP {status} from the MCP tool server"
    return f"failed ({type(root_cause(ex)).__name__})"
