import httpx

from inswa.errors import describe_tool_failure, http_status, is_connection_error, root_cause


def _grouped(leaf: BaseException) -> BaseExceptionGroup:
    return BaseExceptionGroup("unhandled errors in a TaskGroup", [leaf])


def test_root_cause_unwraps_groups_and_chains():
    leaf = ValueError("boom")
    try:
        raise RuntimeError("outer") from leaf
    except RuntimeError as outer:
        assert root_cause(_grouped(outer)) is leaf


def test_connection_failures_are_recognised_through_exception_groups():
    ex = _grouped(httpx.ConnectError("All connection attempts failed"))
    assert is_connection_error(ex)
    assert describe_tool_failure(ex, 30) == "could not reach the MCP tool server"


def test_auth_and_other_http_errors_are_described():
    response = httpx.Response(401, request=httpx.Request("POST", "http://x/mcp"))
    refused = httpx.HTTPStatusError("nope", request=response.request, response=response)
    assert http_status(refused) == 401
    assert "HTTP 401" in describe_tool_failure(refused, 30)


def test_timeout_and_unknown_errors():
    assert describe_tool_failure(TimeoutError(), 12) == "timed out after 12s"
    assert describe_tool_failure(KeyError("x"), 12) == "failed (KeyError)"
