# inswa — agent layer

The agent layer of a conversational Forecasting Assistant for weekly sales volume
(SKU × primary customer), built on
[Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python) (Python).
It answers forecast questions, explains forecast-vs-actual variance and its root causes, and
suggests planner actions. Forecasts are produced by Azure ML batch pipelines; the agent only
**reads and explains** them through MCP tools and never produces forecast figures itself.
Every agent can be deployed as a [Microsoft Foundry hosted agent](https://learn.microsoft.com/en-us/agent-framework/hosting/foundry-hosted-agent).

| Agent | Role key | Intent | Requires | Default |
|---|---|---|---|---|
| Orchestrator | `orchestrator` | — | — | on |
| Forecasting | `forecasting` | `forecast` | — | on |
| Variance Analysis | `variance_analysis` | `variance` | — | on |
| Statistical Explainability | `statistical_explainability` | `explainability` | — | on |
| Root Cause Analysis | `rca` | `root_cause` | variance, explainability | on |
| Recommendations | `market_recommendations` | `recommendation` | rca | on |
| Market Trend | `market_trend` | `market_trend` | — | **off** (`AGENTS__MARKET_TREND__ENABLED`) |

## Architecture

```
            user question (CLI  |  Foundry Responses endpoint /responses)
                                  │
                ┌─────────────────▼──────────────────┐
                │ OrchestratorAgent (hosted agent)   │  conversation memory ◄──► Cosmos (local JSON | Cosmos DB)
                │  Agent Framework Workflow:         │
                │  1 intent ─► 2 scope ─► 3 slots ───┼──► follow-up question if SKU / primary
                │  (router      │          │         │    customer / week is missing
                │   model)  out-of-scope / ▼         │
                │           not enabled  4 delegate ─┼──► specialists in dependency stages
                │                          │         │    (in-process or remote hosted agents)
                │                     5 compose ◄────┼──► AI Search grounding + user feedback
                │                       + figure check│
                └────────────────────────────────────┘
                                  │ grounded answer + citations [E1] [D1], forecast run cited
   specialists ── MCP client (MCPStreamableHTTPTool, Entra token) ──► MCP__URL
                                                         (local mock server | Container App)
   models ── router (GPT-5.4-mini class)  +  reasoning (Claude via AnthropicFoundryClient,
             or GPT via FoundryChatClient), configurable per role
   telemetry ── OpenTelemetry (console | OTLP | Application Insights)
```

The orchestrator steps ([executors.py](src/inswa/orchestration/executors.py)):

1. **Intent.** One structured-output call on the **router** model returns the intents, an
   in-scope flag and the grain slots. Slots are merged with what the conversation already knows;
   weeks are normalised to ISO `YYYY-Www`. A follow-up answer resumes the pending request.
2. **Scope.** Deterministic: refuses out-of-scope questions, answers "not enabled" for switched-off
   agents, and expands the specialists each intent **requires** (root cause → variance + drivers).
3. **Slots.** Requires `sku`, `primary_customer` and `week` (`ORCHESTRATION__REQUIRED_SLOTS`).
4. **Delegate.** Runs specialists stage by stage — e.g. *variance + drivers → RCA →
   recommendations* — concurrently within a stage, each with a timeout. Downstream specialists
   receive upstream evidence as delimited data. A failing specialist becomes `UNAVAILABLE` evidence.
5. **Compose.** Retrieves documents `D1..Dn` and recent user feedback, asks the **reasoning**
   model to answer only from the evidence, then **checks every figure in the answer against the
   tool data and documents**. One retry; if figures still don't match, the answer is withheld
   (`status: grounding_failed`).

### Grounding and safety

- Tools compute everything (variance, totals, percentages); instructions forbid the models from
  computing, rounding or estimating figures, and require naming `forecast_run_id` / `model_version`.
- Evidence and feedback reach models inside `<evidence>` / `<feedback>` elements marked as data;
  tags inside tool output are stripped and each item is length-capped (prompt-injection guard).
- The figure check ([grounding.py](src/inswa/orchestration/grounding.py)) accepts a figure only if it
  occurs in tool data or documents (at the precision shown). Figures from the user's question or
  from specialist prose do not count, so planted or invented numbers are rejected.

## Tool contract (`stub-0.1`, to be agreed with the MCP server team)

All tools take the grain `sku`, `primary_customer`, `week` (ISO week or a date in it) and an
optional `forecast_run_id`, and return the grain plus `forecast_run_id`, `model_version`, `as_of`
and `unit`. See [server.py](src/inswa/mock_mcp_server/server.py).

| Tool | Extra inputs | Returns |
|---|---|---|
| `get_forecast` | `horizon_weeks` (1–26) | weekly `forecast`, `p10`, `p90`; `accuracy` (wMAPE) |
| `analyze_variance` | `lookback_weeks` (1–26) | weekly forecast, actual, variance, variance %, flagged; summary totals |
| `explain_forecast` | — | driver contributions % and direction |
| `get_root_causes` | — | candidate causes with signal and confidence |
| `get_market_recommendations` | — | prioritised planner actions |
| `get_market_trends` | — | placeholder |

## Project layout

```
agents/*.yaml                 agent definitions (declarative kind: Prompt + metadata; draft instructions)
data/search_corpus.json       local AI Search stand-in documents
evals/golden.yaml             golden questions (`inswa eval`)
src/inswa/config/settings.py  the ONLY place environment variables are read
src/inswa/grain.py            ISO week parsing for the forecast grain
src/inswa/agents/             YAML spec loader, registry (flags/routing/stages), factory (clients per role)
src/inswa/orchestration/      workflow models, executors, grounding guards, graph, OrchestratorAgent
src/inswa/tools/mcp.py        MCP client factory (Entra auth)
src/inswa/mock_mcp_server/    local mock of the MCP tool server (contract stub-0.1)
src/inswa/infra/              foundry, secrets, documents (Cosmos), memory, feedback, search, telemetry
src/inswa/hosting/            Foundry hosted-agent entrypoint (ResponsesHostServer)
src/inswa/evals.py, cli.py    golden-set runner; `inswa ask | chat | feedback | eval`
azure.yaml, Dockerfile        azd deployment of every enabled agent as a hosted agent
requirements.lock             locked runtime dependencies for the image
tests/                        offline test suite (test-only fake model client)
```

## Prerequisites

- Python 3.11+ (3.13 recommended)
- A Microsoft Foundry project with model deployments, and `az login`. **There is no local stand-in for Foundry models.**
- Optional: Docker, and the [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) with `azd ext install azure.ai.agents` for deployment.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # set FOUNDRY__PROJECT_ENDPOINT and the model deployments
az login
```

## Run locally

```bash
# 1. local mock MCP tool server (http://localhost:8765/mcp)
python -m inswa.mock_mcp_server

# 2a. CLI (run from the repo root, because agents/, data/ and evals/ paths are relative)
inswa chat
you> What is the forecast for SKU ABC-123 for Contoso?
     -> asks for the week
you> 2026-W46
     -> grounded answer citing [E1] (Forecasting Agent) and the forecast run id

inswa ask "What is the root cause of the forecast miss for SKU 778 at Fabrikam in 2026-W40?"
inswa feedback --conversation-id <id> --rating -1 --comment "show weeks as a table"
inswa eval                                    # golden questions; exit code 1 on any failure

# 2b. or serve as a Foundry hosted agent (Responses protocol on :8088)
python -m inswa.hosting                       # HOSTING__AGENT=orchestrator by default
curl -X POST localhost:8088/responses -H "Content-Type: application/json" \
     -d '{"input": "What is the forecast for SKU ABC-123 for Contoso?", "store": true}'
# continue with "previous_response_id": "<id from the previous response>"
```

The hosted orchestrator serves **stored** requests only: the hosting SDK rejects `"store": false`
for a custom (non-`RawAgent`) agent. Spans go to stderr (`TELEMETRY__EXPORTER=console`); they cover
the workflow, each `orchestrator.*` step, `invoke_agent`, `execute_tool` and MCP `tools/call`.

## Configuration

All configuration is in `.env`; see [.env.example](.env.example) for every key.
[settings.py](src/inswa/config/settings.py) is the only module that reads the environment; a test
(`test_only_settings_module_reads_environment`) enforces this. Nested keys use `__`, e.g.
`COSMOS__PROVIDER`. In a Foundry hosted container the platform injects `FOUNDRY_PROJECT_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` and `APPLICATIONINSIGHTS_CONNECTION_STRING`; these fill the
matching settings when they are not set explicitly.

### Models: router + reasoning, GPT or Claude

| Setting | Meaning |
|---|---|
| `FOUNDRY__DEFAULT_MODEL` / `FOUNDRY__DEFAULT_PROVIDER` | reasoning model (all agent roles) and its API: `openai` or `anthropic` |
| `FOUNDRY__MODELS__ROUTER` / `FOUNDRY__PROVIDERS__ROUTER` | light model for the orchestrator's intent step |
| `FOUNDRY__MODELS__<ROLE>` / `FOUNDRY__PROVIDERS__<ROLE>` | optional per-role override |
| `FOUNDRY__ANTHROPIC_BASE_URL` | Claude endpoint; empty = `https://<account>.services.ai.azure.com/anthropic/` |
| `FOUNDRY__ANTHROPIC_MAX_TOKENS` | Claude max output tokens (default 4096; the client's own default is 1024) |

`anthropic` deployments are called through `AnthropicFoundryClient` with an Entra token
(`https://ai.azure.com/.default`); `openai` deployments through `FoundryChatClient`.

### Swapping a local stand-in for the real service (config only)

| Service | Local (default) | Azure |
|---|---|---|
| MCP tools | `MCP__URL=http://localhost:8765/mcp`, `MCP__AUTH=none` | `MCP__URL=<container app>/mcp`, `MCP__AUTH=entra`, `MCP__SCOPE=api://<mcp-app-id>/.default` |
| Cosmos DB (memory + feedback) | `COSMOS__PROVIDER=local` (JSON under `.local/cosmos`) | `COSMOS__PROVIDER=cosmos`, `COSMOS__ENDPOINT`. **Entra ID only.** Containers `memory` (partition key `/id`) and `feedback` (`/conversation_id`); writes use ETag concurrency |
| Azure AI Search | `SEARCH__PROVIDER=local` (`data/search_corpus.json`) | `SEARCH__PROVIDER=azure`, `SEARCH__ENDPOINT`, `SEARCH__INDEX` (fields `id`, `title`, `content`) |
| Key Vault | `KEYVAULT__PROVIDER=local` (`SECRETS__<NAME>` in `.env`) | `KEYVAULT__PROVIDER=keyvault`, `KEYVAULT__URL` |
| Application Insights | `TELEMETRY__EXPORTER=console` (or `otlp`) | `TELEMETRY__EXPORTER=appinsights` (connection string injected when hosted) |
| Azure auth | `AZURE__CREDENTIAL=cli` | `managed_identity` (+ `AZURE__MANAGED_IDENTITY_CLIENT_ID` for a user-assigned identity) |

### Agents: flags, dependencies and topology

- **Definitions.** `agents/<role>.yaml` uses the Agent Framework declarative `kind: Prompt` shape.
  inswa-specific fields go under `metadata`: `role`, `intents`, `mcp_tools` (an allow-list on the
  MCP server), `requires` (upstream specialists), `hosted_name`, and the orchestrator's `prompts`.
  Instructions are drafts to review with the business. Model deployments are not in YAML.
- **Flags.** `AGENTS__<ROLE>__ENABLED`. A disabled upstream agent is skipped and reported in the answer.
- **Topology.** `AGENTS__<ROLE>__TRANSPORT=inprocess` (default) runs the specialist inside the
  orchestrator; `hosted` calls the separately deployed hosted agent `AGENTS__<ROLE>__HOSTED_NAME`
  through `FoundryAgent` (optionally pinned with `AGENTS__<ROLE>__HOSTED_VERSION`).

## Foundry hosted agents

`python -m inswa.hosting` serves the agent selected by `HOSTING__AGENT` through `ResponsesHostServer`
(Foundry Responses protocol, port 8088).

- **Orchestrator.** A custom `BaseAgent` that runs the workflow per request and keeps its own
  memory keyed by the hosted session id (`history_source="agent"`).
- **Specialists.** A plain `Agent` with its model and MCP tools, built per request, so every
  request gets a fresh MCP connection and a fresh Entra token.
- **Strict mode.** `HOSTING__STRICT=true` (set in azure.yaml) refuses to start with local stand-ins,
  developer credentials, an unauthenticated or localhost MCP server, or a missing App Insights
  connection string, and lists every problem.
- **Telemetry.** The hosting SDK's own observability setup is disabled (`configure_observability=None`)
  so `TELEMETRY__*` stays the single control.

### Deploy with azd

[azure.yaml](azure.yaml) deploys one hosted agent per enabled agent from the same
[Dockerfile](Dockerfile) image (linux/amd64, non-root, locked dependencies), with a different
`HOSTING__AGENT`. It declares two model deployments, `inswa-router` and `inswa-reasoning`
(GPT-5.4-mini stand-in until Claude is deployed).

```bash
azd auth login
azd env set INSWA_MCP_URL https://<mcp-container-app>/mcp
azd env set INSWA_MCP_SCOPE api://<mcp-app-id>/.default
azd env set INSWA_COSMOS_ENDPOINT https://<acct>.documents.azure.com
# Claude as the reasoning model (once deployed in the Foundry resource):
azd env set INSWA_REASONING_MODEL <claude-deployment-name>
azd env set INSWA_REASONING_PROVIDER anthropic
azd env set INSWA_SPECIALIST_TRANSPORT hosted   # optional: orchestrator calls hosted specialists
azd provision && azd deploy
azd ai agent invoke "What is the forecast for SKU ABC-123 for Contoso in 2026-W46?"
```

Each hosted agent gets its own Entra identity; grant it the Cosmos DB data contributor role, the
MCP app role, Foundry model access, and (if used) AI Search / Key Vault roles.

### Dependencies

Agent Framework packages are pinned exactly in [pyproject.toml](pyproject.toml);
`agent-framework-foundry-hosting` and `agent-framework-anthropic` are betas, and naming the beta
version is enough (no `pip install --pre`). The image installs [requirements.lock](requirements.lock),
generated in a `linux/amd64` Python 3.13 container (command in the file header).

## Tests and evals

```bash
pytest           # offline: fake model client + real mock MCP server + real hosting server
inswa eval       # golden questions against the configured models and MCP server
```

The suite uses a **test-only** fake model client (`tests/fakes.py`). It covers config and the
env-access guard, deployment-manifest guards, routing and dependency stages, the follow-up flow,
out-of-scope and disabled answers, the router/reasoning split, Claude vs GPT client selection, the
figure check (retry and fail-closed), prompt-injection neutralisation, specialist timeouts,
feedback in context, ETag concurrency, MCP Entra auth, the weekly tool contract, the golden set,
and an end-to-end run of the hosted orchestrator and a hosted specialist over `/responses`.

## Notes

- Current state of the work, decisions, and open items: [docs/HANDOFF.md](docs/HANDOFF.md).
- The local stores are for development only; strict hosting refuses them.
- `TELEMETRY__SENSITIVE_DATA=true` records prompts, responses and tool arguments. Enable it only in development.
