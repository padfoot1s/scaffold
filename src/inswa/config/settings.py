"""Application settings.

This is the ONLY module in the code base that reads environment variables. Every value
comes from the process environment or the `.env` file and is exposed through typed
settings objects; the rest of the code receives configuration from `get_settings()`.

Nested sections use a double underscore delimiter, e.g. `COSMOS__PROVIDER=local`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AGENT_ROLES: tuple[str, ...] = (
    "orchestrator",
    "forecasting",
    "variance_analysis",
    "statistical_explainability",
    "rca",
    "market_trend",
    "market_recommendations",
)
SPECIALIST_ROLES: tuple[str, ...] = AGENT_ROLES[1:]
# Model roles: every agent role plus the orchestrator's light intent-routing step.
MODEL_ROLES: tuple[str, ...] = ("router", *AGENT_ROLES)

Provider = Literal["openai", "anthropic"]


class AzureAuthSettings(BaseModel):
    """How the process authenticates to Azure services (Foundry, Cosmos, Search, Key Vault, MCP)."""

    credential: Literal["cli", "default", "managed_identity"] = "default"
    managed_identity_client_id: str | None = None


class FoundryModels(BaseModel):
    """Model deployment per model role. Unset roles fall back to `FoundrySettings.default_model`."""

    router: str | None = None
    orchestrator: str | None = None
    forecasting: str | None = None
    variance_analysis: str | None = None
    statistical_explainability: str | None = None
    rca: str | None = None
    market_trend: str | None = None
    market_recommendations: str | None = None


class FoundryProviders(BaseModel):
    """API family per model role. Unset roles fall back to `FoundrySettings.default_provider`."""

    router: Provider | None = None
    orchestrator: Provider | None = None
    forecasting: Provider | None = None
    variance_analysis: Provider | None = None
    statistical_explainability: Provider | None = None
    rca: Provider | None = None
    market_trend: Provider | None = None
    market_recommendations: Provider | None = None


class FoundrySettings(BaseModel):
    project_endpoint: str | None = None
    # Reasoning model used by every role without its own deployment.
    default_model: str | None = None
    models: FoundryModels = FoundryModels()
    # `openai`: Foundry Responses API (FoundryChatClient). `anthropic`: Claude deployed in
    # Foundry, called through the Anthropic Messages API (AnthropicFoundryClient).
    default_provider: Provider = "openai"
    providers: FoundryProviders = FoundryProviders()
    # Claude endpoint; empty = derived from the project endpoint's host (…/anthropic/).
    anthropic_base_url: str | None = None
    # Anthropic requires max_tokens and the client otherwise defaults to 1024.
    anthropic_max_tokens: int = 4096
    token_scope: str = "https://ai.azure.com/.default"

    def model_for(self, role: str) -> str:
        model = getattr(self.models, role, None) or self.default_model
        if not model:
            raise ValueError(
                f"No Foundry model configured for role '{role}'. "
                f"Set FOUNDRY__MODELS__{role.upper()} or FOUNDRY__DEFAULT_MODEL."
            )
        return model

    def provider_for(self, role: str) -> Provider:
        return getattr(self.providers, role, None) or self.default_provider

    def require_endpoint(self) -> str:
        if not self.project_endpoint:
            raise ValueError("FOUNDRY__PROJECT_ENDPOINT (or FOUNDRY_PROJECT_ENDPOINT) is not set.")
        return self.project_endpoint

    def resolved_anthropic_base_url(self) -> str:
        if self.anthropic_base_url:
            return self.anthropic_base_url
        host = urlparse(self.require_endpoint()).netloc
        if not host:
            raise ValueError("Cannot derive the Claude endpoint; set FOUNDRY__ANTHROPIC_BASE_URL.")
        return f"https://{host}/anthropic/"


class AgentToggle(BaseModel):
    """Per-specialist switches: feature flag and where the orchestrator reaches it."""

    enabled: bool = True
    transport: Literal["inprocess", "hosted"] = "inprocess"
    hosted_name: str | None = None
    hosted_version: str | None = None


class AgentsSettings(BaseModel):
    definitions_dir: Path = Path("agents")
    forecasting: AgentToggle = AgentToggle()
    variance_analysis: AgentToggle = AgentToggle()
    statistical_explainability: AgentToggle = AgentToggle()
    rca: AgentToggle = AgentToggle()
    market_trend: AgentToggle = AgentToggle(enabled=False)
    market_recommendations: AgentToggle = AgentToggle()

    def toggle(self, role: str) -> AgentToggle:
        if role not in SPECIALIST_ROLES:
            raise KeyError(f"Unknown specialist role '{role}'.")
        return getattr(self, role)


class OrchestrationSettings(BaseModel):
    # Forecast grain: SKU x primary customer x ISO week.
    required_slots: list[str] = ["sku", "primary_customer", "week"]
    specialist_timeout_seconds: float = 90
    # Per evidence item, so one large tool payload cannot crowd out the rest of the prompt.
    max_evidence_chars: int = 8000
    # Reject answers containing figures that do not appear in tool data, documents or the question.
    grounding_check: bool = True
    max_feedback_items: int = 3


class McpSettings(BaseModel):
    url: str = "http://localhost:8765/mcp"
    # `entra`: managed-identity bearer token for `scope` (e.g. api://<mcp-app-id>/.default).
    auth: Literal["none", "entra"] = "none"
    scope: str | None = None
    request_timeout: int = 30
    mock_host: str = "127.0.0.1"
    mock_port: int = 8765

    @model_validator(mode="after")
    def _scope_required_for_entra(self) -> McpSettings:
        if self.auth == "entra" and not self.scope:
            raise ValueError("MCP__SCOPE must be set when MCP__AUTH=entra.")
        return self


class CosmosSettings(BaseModel):
    """Entra ID auth only (key auth is disabled on the account)."""

    provider: Literal["local", "cosmos"] = "local"
    endpoint: str | None = None
    database: str = "inswa"
    memory_container: str = "memory"  # partition key /id (= conversation id)
    feedback_container: str = "feedback"  # partition key /conversation_id
    local_path: Path = Path(".local/cosmos")


class SearchSettings(BaseModel):
    provider: Literal["local", "azure"] = "local"
    endpoint: str | None = None
    index: str = "inswa-grounding"
    api_key_secret: str | None = None
    local_corpus: Path = Path("data/search_corpus.json")
    top_k: int = 3


class KeyVaultSettings(BaseModel):
    provider: Literal["local", "keyvault"] = "local"
    url: str | None = None


class TelemetrySettings(BaseModel):
    exporter: Literal["console", "otlp", "appinsights", "none"] = "console"
    otlp_endpoint: str = "http://localhost:4317"
    appinsights_connection_string: str | None = None
    service_name: str = "inswa-agents"
    sensitive_data: bool = False


class HostingSettings(BaseModel):
    agent: str = "orchestrator"
    host: str = "0.0.0.0"
    port: int = 8088
    # Set in deployed containers: refuse to start on local stand-ins or developer credentials.
    strict: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    azure: AzureAuthSettings = AzureAuthSettings()
    foundry: FoundrySettings = FoundrySettings()
    agents: AgentsSettings = AgentsSettings()
    orchestration: OrchestrationSettings = OrchestrationSettings()
    mcp: McpSettings = McpSettings()
    cosmos: CosmosSettings = CosmosSettings()
    search: SearchSettings = SearchSettings()
    keyvault: KeyVaultSettings = KeyVaultSettings()
    telemetry: TelemetrySettings = TelemetrySettings()
    hosting: HostingSettings = HostingSettings()
    # Local stand-in for Key Vault: SECRETS__<NAME>=<value>
    secrets: dict[str, str] = {}

    # Variables injected by the Foundry hosted-agent runtime. They fill the nested
    # settings above when those are not set explicitly.
    hosted_project_endpoint: str | None = Field(
        default=None, validation_alias=AliasChoices("FOUNDRY_PROJECT_ENDPOINT")
    )
    hosted_model_deployment: str | None = Field(
        default=None, validation_alias=AliasChoices("AZURE_AI_MODEL_DEPLOYMENT_NAME", "FOUNDRY_MODEL")
    )
    hosted_appinsights_connection_string: str | None = Field(
        default=None, validation_alias=AliasChoices("APPLICATIONINSIGHTS_CONNECTION_STRING")
    )

    @model_validator(mode="after")
    def _apply_hosted_runtime_values(self) -> Settings:
        if not self.foundry.project_endpoint and self.hosted_project_endpoint:
            self.foundry.project_endpoint = self.hosted_project_endpoint
        if not self.foundry.default_model and self.hosted_model_deployment:
            self.foundry.default_model = self.hosted_model_deployment
        if not self.telemetry.appinsights_connection_string and self.hosted_appinsights_connection_string:
            self.telemetry.appinsights_connection_string = self.hosted_appinsights_connection_string
        return self

    def deployment_problems(self) -> list[str]:
        """Why this configuration must not run in a deployed container (empty = fine)."""
        problems = []
        if self.azure.credential != "managed_identity":
            problems.append("AZURE__CREDENTIAL must be managed_identity.")
        if self.cosmos.provider != "cosmos" or not self.cosmos.endpoint:
            problems.append(
                "COSMOS__PROVIDER=cosmos and COSMOS__ENDPOINT are required (local JSON is not durable)."
            )
        host = urlparse(self.mcp.url).hostname or ""
        if not host or host in ("localhost", "127.0.0.1", "0.0.0.0"):
            problems.append(f"MCP__URL must point at the deployed MCP server, got '{self.mcp.url}'.")
        if self.mcp.auth != "entra":
            problems.append("MCP__AUTH must be entra.")
        if self.telemetry.exporter == "appinsights" and not self.telemetry.appinsights_connection_string:
            problems.append(
                "APPLICATIONINSIGHTS_CONNECTION_STRING is required for TELEMETRY__EXPORTER=appinsights."
            )
        try:
            self.foundry.require_endpoint()
            for role in MODEL_ROLES:
                self.foundry.model_for(role)
        except ValueError as ex:
            problems.append(str(ex))
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
