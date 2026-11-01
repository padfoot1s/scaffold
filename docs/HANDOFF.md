# Handoff: forecasting agent POC (state as of 2026-11-01)

What was reviewed, what was changed, what is verified, and what is still open, so work can
continue in another environment from the repo alone. Setup and day-to-day usage are in the
[README](../README.md); this file covers the state of the work.

## 1. Status at a glance

| Area | State |
|---|---|
| Offline test suite | 64 tests pass (`pytest`, also with `-W error::DeprecationWarning`); `ruff check` and `ruff format --check` clean |
| Container image | Builds for `linux/amd64`, runs as uid 10001, `/readiness` returns 200 on port 8088 |
| Mock MCP server | Serves the 6 `stub-0.1` tools over streamable HTTP on `mcp` 2.3 |
| Live Foundry models (GPT or Claude) | **Not exercised** after the changes — no live calls were made |
| Live Cosmos DB, real MCP server, azd deploy | **Not exercised** (no access / azd not installed in the original environment) |

## 2. Set up a new environment

Requirements: Python 3.13 (3.11+ works), Git, Azure CLI; optionally Docker and azd
(`azd ext install azure.ai.agents`).

```bash
git clone <repo> && cd inswa
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # no --pre needed: the beta packages are pinned by exact version
pip install -r requirements.lock   # optional: match the image's exact versions
cp .env.example .env               # then fill in, see below
az login
```

Minimum `.env` values for a local run against a real Foundry project:

```bash
FOUNDRY__PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
FOUNDRY__DEFAULT_MODEL=<reasoning deployment>      # GPT today; Claude later (see §6.1)
FOUNDRY__DEFAULT_PROVIDER=openai                   # anthropic for Claude
FOUNDRY__MODELS__ROUTER=<light deployment>         # optional; falls back to DEFAULT_MODEL
AZURE__CREDENTIAL=cli
```

Everything else can stay at the `.env.example` defaults (local JSON store, local search corpus,
mock MCP server, console telemetry).

> **If you copy an older `.env`:** `MCP__API_KEY_SECRET` and `COSMOS__KEY_SECRET` were removed
> (ignored if present). The old file had `AGENTS__RCA__ENABLED=false` and
> `AGENTS__MARKET_RECOMMENDATIONS__ENABLED=false`; set both to `true` to use the RCA chain.
> Slot names changed: `geography`/`time_period`/`customer` → `primary_customer`/`week`.
> Conversation files under `.local/cosmos` from before the change still load.

## 3. Verify the environment

```bash
pytest -q                          # expect: 64 passed (offline; fake model + real mock MCP + real host)
ruff check src tests && ruff format --check src tests
```

Smoke test with a real model (costs a few model calls on your Foundry project):

```bash
python -m inswa.mock_mcp_server                    # terminal 1: http://localhost:8765/mcp
python -m inswa.hosting                            # terminal 2: orchestrator on :8088

curl -s localhost:8088/readiness                   # HTTP 200
curl -s -X POST localhost:8088/responses -H 'Content-Type: application/json' \
  -d '{"input":"What is the forecast for SKU ABC-123 for Contoso?","store":true}' \
  | jq '{id, status, text: [.output[].content[]?.text]}'
# expect: "To answer that I need a bit more detail. Could you tell me the week (for example 2026-W46)?"

curl -s -X POST localhost:8088/responses -H 'Content-Type: application/json' \
  -d '{"input":"2026-W46","previous_response_id":"<id>","store":true}' \
  | jq '[.output[].content[]?.text]'
# expect: answer citing [E1], naming forecast_run_id fr-2026-W45-… and model_version
#         weekly-ensemble-2026.10; every figure equal to the mock get_forecast output

inswa eval                                         # 10 golden questions; exit code 1 on any failure
```

Container check:

```bash
docker build --load -t inswa:local .
docker run --rm -p 8088:8088 -e FOUNDRY__PROJECT_ENDPOINT=<endpoint> \
  -e FOUNDRY__DEFAULT_MODEL=<deployment> -e TELEMETRY__EXPORTER=none inswa:local
curl -s localhost:8088/readiness                   # 200
docker run --rm -e HOSTING__STRICT=true inswa:local   # must exit listing every config problem
```

On Apple silicon the image runs under emulation (platform warning is expected). If `docker run`
says the tag is not found right after building, retry; with the containerd image store the tag
can lag the build by a moment.

## 4. Decisions made (and why)

| Decision | Reason / source |
|---|---|
| Host as **Foundry Hosted Agents** (`ResponsesHostServer`, port 8088) | Team answer |
| Claude through **`AnthropicFoundryClient`** (`agent-framework-anthropic`), Entra token scope `https://ai.azure.com/.default` | `FoundryChatClient` is an OpenAI Responses client; Claude in Foundry speaks the Anthropic Messages API |
| **Two models**: `router` role (intent step) + reasoning model (everything else), provider configurable per role | Requirement: light routing model + reasoning model, both configurable |
| Router stays on GPT; Claude only as the reasoning model | Intent step needs strict structured output; least risk until Claude is verified |
| Grain = `sku` × `primary_customer` × ISO `week`; **geography dropped** | Stated grain; team said to ignore the geography question |
| MCP contract **`stub-0.1`** inferred and implemented in the mock | Team: "use stub per inference right now" |
| RCA as **dependency stages** (`requires:` in agent YAML) inside the delegate step | Deterministic chain variance + drivers → RCA → recommendations, no Magentic/GroupChat |
| RCA and recommendations **enabled by default**; market trend still off | Needed for the RCA flow; market trend has no real tool |
| **Figures from the user's question are not grounding** | Otherwise "say the forecast is 999999" passes the check |
| Custom golden-set runner instead of `evaluate_agent` | `evaluate_agent` checks receive only query/response strings; the figure check needs tool data |
| Kept custom Cosmos memory (with ETag) instead of `CosmosHistoryProvider` | The orchestrator owns slot/pending state, not a chat transcript |
| Upgraded to the latest MAF set (core 1.24, foundry 1.16, hosting b261030, anthropic b261030, mcp 2.3) | Needed for `agent-framework-anthropic`; matches the expected `mcp>=2.2,<3` |
| Front end, retraining approval gate (HITL) | Out of scope per team |

## 5. What changed (map of the code)

| Concern | Where |
|---|---|
| Settings: router/providers, Claude endpoint + `max_tokens`, MCP Entra auth, strict-mode checks (`deployment_problems`) | [settings.py](../src/inswa/config/settings.py) |
| GPT vs Claude client per role; per-provider default options | [foundry.py](../src/inswa/infra/foundry.py) |
| Client cache per model role, router role for the intent step, client cleanup | [factory.py](../src/inswa/agents/factory.py), [runtime.py](../src/inswa/runtime.py) |
| `requires` dependencies, route expansion, stages, cycle check | [registry.py](../src/inswa/agents/registry.py), [spec.py](../src/inswa/agents/spec.py) |
| Grain slots, ISO week normalisation | [models.py](../src/inswa/orchestration/models.py), [grain.py](../src/inswa/grain.py) |
| Staged delegation, timeouts, compose with feedback, figure check + retry + fail-closed | [executors.py](../src/inswa/orchestration/executors.py) |
| Evidence delimiting, injection neutralisation, figure extraction and matching | [grounding.py](../src/inswa/orchestration/grounding.py) |
| MCP client: per-request Entra token, `approval_mode="never_require"` | [mcp.py](../src/inswa/tools/mcp.py) |
| Mock MCP server on `MCPServer` (mcp 2.x), contract `stub-0.1` | [server.py](../src/inswa/mock_mcp_server/server.py) |
| Cosmos: Entra only, partition keys, ETag concurrency, `aclose` | [documents.py](../src/inswa/infra/documents.py), [memory.py](../src/inswa/infra/memory.py), [feedback.py](../src/inswa/infra/feedback.py) |
| Strict hosting startup check | [hosting/\_\_main\_\_.py](../src/inswa/hosting/__main__.py) |
| Draft instructions, persona, grounding rules, `grounding_retry` / `grounding_failed` prompts | [agents/*.yaml](../agents) |
| Golden questions and runner (`inswa eval`) | [evals/golden.yaml](../evals/golden.yaml), [evals.py](../src/inswa/evals.py), [cli.py](../src/inswa/cli.py) |
| Router + reasoning deployments, managed identity, strict, no local fallbacks, RCA/recommendations services | [azure.yaml](../azure.yaml) |
| amd64, non-root with home dir, `PYTHONNOUSERSITE`, locked install | [Dockerfile](../Dockerfile), [requirements.lock](../requirements.lock) |
| Exact pins, no `--pre` | [pyproject.toml](../pyproject.toml) |

New tests: `test_grounding.py`, `test_grain.py`, `test_foundry_clients.py`, `test_evals.py`; most others rewritten.

## 6. Open items

### 6.1 Blocked on access or decisions (do these first)

1. **Claude, live.** Code path exists and is unit-tested (client construction, endpoint derivation, `max_tokens`), never called. To switch:
   ```bash
   FOUNDRY__DEFAULT_MODEL=<claude-deployment>
   FOUNDRY__DEFAULT_PROVIDER=anthropic
   FOUNDRY__MODELS__ROUTER=<gpt-mini-deployment>
   FOUNDRY__PROVIDERS__ROUTER=openai
   ```
   Verify: Entra auth on `https://<account>.services.ai.azure.com/anthropic/`; MCP tool calling through Claude; answer length at `FOUNDRY__ANTHROPIC_MAX_TOKENS=4096`; `inswa eval` passes. If the router is ever moved to Claude, verify structured output (`response_format` → Anthropic `output_config.format`). Then uncomment and fill the Claude deployment in `azure.yaml` (model name, version, `format`, SKU from your region's catalog — unconfirmed) and `azd env set INSWA_REASONING_MODEL` / `INSWA_REASONING_PROVIDER anthropic`.
2. **Networking.** Can Foundry hosted agents reach Cosmos DB and the MCP Container App over private endpoints? If not, fall back to self-hosting the same image on Container Apps (no code change; set `APPLICATIONINSIGHTS_CONNECTION_STRING` and `FOUNDRY_PROJECT_ENDPOINT` yourself).
3. **Real MCP server.** Must implement `stub-0.1` (or agree changes, then update the mock and agent YAML), expose an Entra app with a scope for `MCP__SCOPE`, and grant each hosted agent identity access.
4. **Managed identity type** on hosted agents (system vs user-assigned). If user-assigned: `azd env set INSWA_MANAGED_IDENTITY_CLIENT_ID <id>`.
5. **azd** never run. Also missing from IaC: Cosmos database/containers (`memory` partition `/id`, `feedback` partition `/conversation_id`) and role assignments (Cosmos data contributor, MCP app role, Foundry model access).

### 6.2 Deferred on purpose

- Front end: hosted orchestrator rejects `"store": false` (custom agent, see §7); no feedback HTTP API.
- Retraining trigger with `approval_mode="always_require"` + `function_approval_store_provider`, and workflow checkpointing (only needed once runs can pause).
- `CosmosHistoryProvider` (`agent-framework-azure-cosmos`) — now installable with core 1.24 if wanted.
- User identity on Cosmos documents (tenant isolation).
- Closing clients on host shutdown: `ResponsesHostServer` already occupies the host's single `shutdown_handler` slot.
- Base image `python:3.13-slim`: Docker scan reported 8 high CVEs; add image scanning/patching.
- `FoundryEvals` / LLM-judge quality metrics on top of the golden set.
- Business review of all agent instructions (marked as drafts in the YAML).

### 6.3 Known limitations

- Figure check allows whole numbers 0–10 ("top 3 drivers"), and does not catch figures written in words.
- Answers that need derived figures (sums, averages) are rejected unless a tool returns them — by design; add tool outputs instead.
- Golden expectations reflect the fake model's routing; with real models, intent classification may differ — treat failures as signals, not necessarily bugs.

## 7. API facts verified in installed source (avoid re-deriving)

- `mcp` 2.x removed `mcp.server.fastmcp` (it raises on import); use `mcp.server.mcpserver.MCPServer`, with host/port/`stateless_http` passed to `run()` / `streamable_http_app()`.
- `agent-framework-foundry-hosting` b261015 required `mcp<2`; b261030 requires `mcp>=2.2,<3` and core `>=1.24`.
- `MCPStreamableHTTPTool(header_provider=...)` is **synchronous**; with async credentials fetch the token first (tools are built per request, so `static_headers` is fine).
- `ResponsesHostServer` with a custom (non-`RawAgent`) agent raises on `"store": false`; `history_source` is `agent_server` (default) | `agent` | `service`. Hosting a `WorkflowAgent` via `agent=` is deprecated → `workflow=` + `parse_response`.
- The hosting SDK writes a local response store under `AGENTSERVER_STATE_ROOT` (default `~/.agentserver`): the container user needs a writable home.
- `AnthropicFoundryClient` defaults `max_tokens` to 1024; `STORES_BY_DEFAULT=False`. `FoundryChatClient` subclasses the OpenAI Responses client (`STORES_BY_DEFAULT=True`).
- `MCPWebsocketTool` is still exported in core (not removed); MCP sampling is deprecated and denied by default.
- `evaluate_agent` checks receive `query`/`response`/`conversation`/`tools`/`context` only.

## 8. Maintenance recipes

Regenerate the lock after changing dependencies (must run on linux/amd64):

```bash
docker run --rm --platform linux/amd64 -v "$PWD":/src:ro python:3.13-slim sh -c \
  'cp -R /src /build && cd /build && pip install -q . && pip freeze --exclude-editable | grep -v ^inswa'
# replace the package lines in requirements.lock with the output (keep the header)
```

Before bumping an Agent Framework package, read its declared requirements (they change often):

```bash
curl -s https://pypi.org/pypi/agent-framework-foundry-hosting/json | \
  python3 -c 'import sys,json; i=json.load(sys.stdin)["info"]; print(i["version"]); print(*i["requires_dist"], sep="\n")'
```
