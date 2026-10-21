"""Runs a hosted agent server with the test-only fake model (used by test_hosting_e2e.py).

python tests/hosting_harness.py <agent> <port> <mcp_url> <tmp_dir>
"""

import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inswa.hosting.__main__ as hosting  # noqa: E402
from tests.conftest import make_settings  # noqa: E402
from tests.fakes import FakeChatClient  # noqa: E402

agent, port, mcp_url, tmp_dir = sys.argv[1], int(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
hosting.create_runtime = functools.partial(hosting.create_runtime, chat_client_factory=FakeChatClient)
server = hosting.build_server(make_settings(tmp_dir, mcp_url, hosting={"agent": agent}))
server.run(host="127.0.0.1", port=port)
