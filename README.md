# inswa — agent layer

The agent layer of a demand-planning insights assistant, built on
[Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/?pivots=programming-language-python) (Python).
Every agent can be deployed as a [Microsoft Foundry hosted agent](https://learn.microsoft.com/en-us/agent-framework/hosting/foundry-hosted-agent).

| Agent | Role key | Default |
|---|---|---|
| Orchestrator | `orchestrator` | on |
| Forecasting | `forecasting` | on |
| Variance Analysis | `variance_analysis` | on |
| Statistical Explainability | `statistical_explainability` | on |
| Root Cause Analysis | `rca` | **off** (`AGENTS__RCA__ENABLED`) |
| Market Trend | `market_trend` | **off** (`AGENTS__MARKET_TREND__ENABLED`) |
| Market Recommendations | `market_recommendations` | **off** (`AGENTS__MARKET_RECOMMENDATIONS__ENABLED`) |

## Architecture

```
            user question (CLI  |  Foundry Responses endpoint /responses)
                                  │
                ┌─────────────────▼──────────────────┐
                │ OrchestratorAgent (hosted agent)   │  conversation memory ◄──► Cosmos (local JSON | Cosmos DB)
                │  Agent Framework Workflow:         │
                │  1 intent ─► 2 scope ─► 3 slots ───┼──► follow-up question if geography /
                │                 │          │       │    time period / customer / SKU missing
                │          out-of-scope /    ▼       │
                │          not enabled  4 delegate ──┼──► specialists in parallel (in-process or
                │                            │       │    remote Foundry hosted agents, per config)
                │                       5 compose ◄──┼──► AI Search grounding (local JSON | Azure AI Search)
                └────────────────────────────────────┘
                                  │ grounded answer + citations [E1] [D1]
   specialists ── MCP client (MCPStreamableHTTPTool) ──► MCP__URL
                                                         (local mock server | real tool server)
   all models ── FoundryChatClient (model deployment per agent role)
   secrets ── Key Vault (local .env SECRETS__* | Azure Key Vault)
   telemetry ── OpenTelemetry (console | OTLP | Application Insights)
```

Here is what each orchestrator step does ([src/inswa/orchestration/executors.py](src/inswa/orchestration/executors.py)):

1. **Intent.** One structured-output call on the orchestrator model returns the intents, an in-scope flag and the extracted slots. The slots are merged with what the conversation already knows. If the user is answering a follow-up question, the pending request resumes.
2. **Scope.** A deterministic check. It refuses out-of-scope questions. It answers "not enabled" when the intent belongs to a switched-off agent.
3. **Slots.** The step needs `geography`, `time_period`, `customer` and `sku` (configurable in `OrchestrationSettings`). If any are missing, it asks one follow-up question and saves the partial request to memory.
4. **Delegate.** It runs every enabled specialist for the intents concurrently. Each specialist calls its MCP tool, and its output plus the tool data become evidence `E1..En`.
5. **Compose.** It retrieves grounding documents `D1..Dn`, then asks the orchestrator model to answer **only** from that evidence, with citations.

## Project layout

```
agents/*.yaml                 placeholder agent definitions (declarative kind: Prompt + metadata)
data/search_corpus.json       local AI Search stand-in documents
src/inswa/config/settings.py  the ONLY place environment variables are read
src/inswa/agents/             YAML spec loader, registry (flags/routing), factory (Agent | FoundryAgent)
src/inswa/orchestration/      workflow models, executors, graph, OrchestratorAgent
src/inswa/tools/mcp.py        MCP client factory
src/inswa/mock_mcp_server/    local mock Forecast / Variance Analyzer / Explainability MCP server
src/inswa/infra/              foundry, secrets, documents (Cosmos), memory, feedback, search, telemetry
src/inswa/hosting/            Foundry hosted-agent entrypoint (ResponsesHostServer)
src/inswa/cli.py              `inswa ask | chat | feedback`
azure.yaml, Dockerfile        azd deployment of every agent as a hosted agent
tests/                        offline test suite (test-only fake model client)
```

## Prerequisites

- Python 3.11+ (3.13 recommended)
- A Microsoft Foundry project with a model deployment, and `az login`. **There is no local stand-in for Foundry models.**
- Optional: Docker, and the [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) with `azd ext install azure.ai.agents` for deployment.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --pre -e ".[dev]"
cp .env.example .env      # then set FOUNDRY__PROJECT_ENDPOINT and FOUNDRY__DEFAULT_MODEL
az login
```

## Run locally

```bash
# 1. local mock MCP tool server (http://localhost:8765/mcp)
python -m inswa.mock_mcp_server

# 2a. CLI (run from the repo root, because agents/ and data/ paths are relative)
inswa chat
you> What is the demand forecast for SKU ABC-123 for Contoso?
     -> asks for the geography and time period
you> EMEA, Q3 2026
     -> grounded answer citing [E1] (Forecasting Agent) and [D1..] (documents)

inswa ask "Explain the drivers and variance vs actuals for SKU 9 for Fabrikam in APAC Q1 2026"
inswa feedback --conversation-id <id> --rating 1 --comment "useful"

# 2b. or serve as a Foundry hosted agent (Responses protocol on :8088)
python -m inswa.hosting                       # HOSTING__AGENT=orchestrator by default
curl -X POST localhost:8088/responses -H "Content-Type: application/json" \
     -d '{"input": "What is the demand forecast for SKU ABC-123 for Contoso?", "store": true}'
# continue the conversation with "previous_response_id": "<id from the previous response>"
```

Spans go to stderr (`TELEMETRY__EXPORTER=console`). They cover the workflow, each `orchestrator.*` step, `invoke_agent`, `execute_tool` and MCP `tools/call`.

## Configuration

All configuration is in `.env`; see [.env.example](.env.example) for every key. [settings.py](src/inswa/config/settings.py) is the only module that reads the environment. Everything else receives typed settings, and values are passed explicitly into the SDKs, so nothing depends on SDKs reading env vars implicitly. A test (`test_only_settings_module_reads_environment`) enforces this.

Nested keys use `__`, e.g. `COSMOS__PROVIDER`. In a Foundry hosted container, the platform injects `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME` and `APPLICATIONINSIGHTS_CONNECTION_STRING`. These are used as fallbacks for the matching settings.

### Swapping a local stand-in for the real service (config only)

| Service | Local (default) | Switch to Azure |
|---|---|---|
| Foundry models | none | `FOUNDRY__PROJECT_ENDPOINT`, `FOUNDRY__DEFAULT_MODEL`, optional `FOUNDRY__MODELS__<ROLE>` per agent role |
| MCP tools | `MCP__URL=http://localhost:8765/mcp` (mock) | `MCP__URL=<real server>`, optional `MCP__API_KEY_SECRET=<secret name>` (sent as Bearer token) |
| Cosmos DB (memory + feedback) | `COSMOS__PROVIDER=local` (JSON under `.local/cosmos`) | `COSMOS__PROVIDER=cosmos`, `COSMOS__ENDPOINT`, `COSMOS__DATABASE`, containers `COSMOS__MEMORY_CONTAINER` / `COSMOS__FEEDBACK_CONTAINER` (partition key `/id`). Entra ID auth, or `COSMOS__KEY_SECRET` |
| Azure AI Search | `SEARCH__PROVIDER=local` (`data/search_corpus.json`) | `SEARCH__PROVIDER=azure`, `SEARCH__ENDPOINT`, `SEARCH__INDEX` (fields `id`, `title`, `content`). Entra ID auth, or `SEARCH__API_KEY_SECRET` |
| Key Vault | `KEYVAULT__PROVIDER=local` (`SECRETS__<NAME>` in `.env`) | `KEYVAULT__PROVIDER=keyvault`, `KEYVAULT__URL` |
| Application Insights | `TELEMETRY__EXPORTER=console` (or `otlp` for e.g. an Aspire dashboard) | `TELEMETRY__EXPORTER=appinsights`, `TELEMETRY__APPINSIGHTS_CONNECTION_STRING` (injected automatically when hosted) |
| Azure auth | `AZURE__CREDENTIAL=cli` | `default` or `managed_identity` (+ `AZURE__MANAGED_IDENTITY_CLIENT_ID`) |

### Agents: flags, models and topology

- **Definitions.** `agents/<role>.yaml` uses the Agent Framework declarative `kind: Prompt` shape (`name`, `description`, `instructions`, `model.options`). inswa-specific fields go under `metadata`: `role`, `intents`, `mcp_tools` (an allow-list on the MCP server), `hosted_name`, and the orchestrator's step `prompts`. All instructions are placeholders. Model deployment ids are not in YAML; they come from `FOUNDRY__MODELS__<ROLE>`.
- **Turning on a disabled agent.** Set, for example, `AGENTS__RCA__ENABLED=true`. The agent's YAML and mock tool already exist; replace the placeholder instructions and point `MCP__URL` at a server that implements the tool.
- **Topology.** `AGENTS__<ROLE>__TRANSPORT=inprocess` (the default) runs the specialist inside the orchestrator. `hosted` calls the separately deployed Foundry hosted agent named `AGENTS__<ROLE>__HOSTED_NAME` through `FoundryAgent`. You can also pin `AGENTS__<ROLE>__HOSTED_VERSION`.

## Foundry hosted agents

`python -m inswa.hosting` serves the agent selected by `HOSTING__AGENT` through `ResponsesHostServer`. This is the Foundry Responses protocol on port 8088, the same contract the platform uses.

- **Orchestrator.** A custom `BaseAgent` that runs the workflow on every request. It keeps its own memory, keyed by the hosted session id (`history_source="agent"`).
- **Specialists.** A plain `Agent` with a Foundry model and MCP tools. A new instance is built per request, so each request gets fresh MCP connections, as the hosting docs recommend.
- **Telemetry.** The hosting SDK's own env-driven observability setup is disabled (`configure_observability=None`) so that `TELEMETRY__*` stays the single control.

### Deploy with azd

[azure.yaml](azure.yaml) deploys one hosted agent per enabled agent. All of them use the same [Dockerfile](Dockerfile) image, with a different `HOSTING__AGENT`.

**Models per agent.** Each enabled agent role has its own model deployment, named `inswa-<role>-model`, plus a `gpt-5.4-mini` fallback deployment.
- Every container receives all `FOUNDRY__MODELS__<ROLE>` settings. The orchestrator needs them because it can run specialists in-process.
- To change one agent's model, edit its deployment's `model` in `azure.yaml`, or point the role at another deployment with `azd env set INSWA_MODEL_<ROLE> <deployment-name>`.
- Disabled agents fall back to `AZURE_AI_MODEL_DEPLOYMENT_NAME` until you give them a deployment.
- Five deployments at capacity 10 each need matching quota in your region.

```bash
azd auth login
azd env set INSWA_MCP_URL https://<your-mcp-server>/mcp
azd env set INSWA_COSMOS_PROVIDER cosmos && azd env set INSWA_COSMOS_ENDPOINT https://<acct>.documents.azure.com
azd env set INSWA_SEARCH_PROVIDER azure  && azd env set INSWA_SEARCH_ENDPOINT https://<svc>.search.windows.net
azd env set INSWA_SPECIALIST_TRANSPORT hosted   # optional: orchestrator calls hosted specialists
azd provision && azd deploy
azd ai agent invoke "What is the demand forecast for SKU ABC-123 for Contoso in EMEA for Q3 2026?"
```

You can also test locally through azd: `azd ai agent run` and then `azd ai agent invoke --local "..."`. Each hosted agent gets its own Entra identity; grant it RBAC on Cosmos DB, AI Search and Key Vault.

## Tests

```bash
pytest
```

The suite runs fully offline. It uses a **test-only** fake model client (`tests/fakes.py`), which is not a configurable stand-in. Against the real mock MCP server and the real hosting server, it covers:

- config parsing and the env-access guard
- the flags and routing
- the follow-up flow and slot memory
- out-of-scope and disabled-capability answers
- fan-out to several specialists
- the hosted-transport switch
- the local stores
- the MCP tool calls
- an end-to-end run of the hosted orchestrator and a hosted specialist over `/responses`

## Notes

- `agent-framework-foundry-hosting` is a prerelease (`pip install --pre`). It requires `mcp<2`, so `mcp` is pinned to `>=1.24,<2`.
- The local stores are for development only. A hosted container's working directory isn't durable, so configure Cosmos DB for hosted deployments.
- `TELEMETRY__SENSITIVE_DATA=true` records prompts, responses and tool arguments. Enable it only in development.
