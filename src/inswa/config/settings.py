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


class AzureAuthSettings(BaseModel):
    """How the process authenticates to Azure services (Foundry, Cosmos, Search, Key Vault)."""

    credential: Literal["cli", "default", "managed_identity"] = "default"
    managed_identity_client_id: str | None = None


class FoundryModels(BaseModel):
    """Model deployment per agent role. Unset roles fall back to `FoundrySettings.default_model`."""

    orchestrator: str | None = None
    forecasting: str | None = None
    variance_analysis: str | None = None
    statistical_explainability: str | None = None
    rca: str | None = None
    market_trend: str | None = None
    market_recommendations: str | None = None


class FoundrySettings(BaseModel):
    project_endpoint: str | None = None
    default_model: str | None = None
    models: FoundryModels = FoundryModels()

    def model_for(self, role: str) -> str:
        model = getattr(self.models, role, None) or self.default_model
        if not model:
            raise ValueError(
                f"No Foundry model configured for role '{role}'. "
                f"Set FOUNDRY__MODELS__{role.upper()} or FOUNDRY__DEFAULT_MODEL."
            )
        return model

    def require_endpoint(self) -> str:
        if not self.project_endpoint:
            raise ValueError("FOUNDRY__PROJECT_ENDPOINT (or FOUNDRY_PROJECT_ENDPOINT) is not set.")
        return self.project_endpoint


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
    rca: AgentToggle = AgentToggle(enabled=False)
    market_trend: AgentToggle = AgentToggle(enabled=False)
    market_recommendations: AgentToggle = AgentToggle(enabled=False)

    def toggle(self, role: str) -> AgentToggle:
        if role not in SPECIALIST_ROLES:
            raise KeyError(f"Unknown specialist role '{role}'.")
        return getattr(self, role)


class OrchestrationSettings(BaseModel):
    required_slots: list[str] = ["geography", "time_period", "customer", "sku"]


class McpSettings(BaseModel):
    url: str = "http://localhost:8765/mcp"
    api_key_secret: str | None = None
    request_timeout: int = 30
    mock_host: str = "127.0.0.1"
    mock_port: int = 8765


class CosmosSettings(BaseModel):
    provider: Literal["local", "cosmos"] = "local"
    endpoint: str | None = None
    database: str = "inswa"
    memory_container: str = "memory"
    feedback_container: str = "feedback"
    key_secret: str | None = None
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
