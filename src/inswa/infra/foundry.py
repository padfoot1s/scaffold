"""Microsoft Foundry connections: credentials, per-role chat clients and remote hosted agents.

There is intentionally no local stand-in for Foundry models.
"""

from __future__ import annotations

from typing import Any

from agent_framework.foundry import AnthropicFoundryClient, FoundryAgent, FoundryChatClient
from azure.identity.aio import (
    AzureCliCredential,
    DefaultAzureCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)

from inswa.config import Settings


def create_credential(settings: Settings) -> Any:
    """Async Azure credential shared by Foundry, Cosmos, AI Search, Key Vault and MCP calls."""
    client_id = settings.azure.managed_identity_client_id or None
    match settings.azure.credential:
        case "cli":
            return AzureCliCredential()
        case "managed_identity":
            return ManagedIdentityCredential(client_id=client_id)
        case _:
            return DefaultAzureCredential(managed_identity_client_id=client_id)


def create_chat_client(
    settings: Settings, role: str, credential: Any
) -> FoundryChatClient | AnthropicFoundryClient:
    """Chat client for the model deployment configured for `role`.

    `openai` deployments use the Foundry Responses API; `anthropic` (Claude) deployments use the
    Anthropic Messages API on the same Foundry resource, authenticated with an Entra token.
    """
    foundry = settings.foundry
    model = foundry.model_for(role)
    if foundry.provider_for(role) == "anthropic":
        return AnthropicFoundryClient(
            model=model,
            base_url=foundry.resolved_anthropic_base_url(),
            azure_ad_token_provider=get_bearer_token_provider(credential, foundry.token_scope),
        )
    return FoundryChatClient(project_endpoint=foundry.require_endpoint(), model=model, credential=credential)


def default_model_options(settings: Settings, role: str) -> dict[str, Any]:
    """Provider-specific run options every agent on `role` needs."""
    if settings.foundry.provider_for(role) == "anthropic":
        return {"max_tokens": settings.foundry.anthropic_max_tokens}
    return {}


def create_remote_hosted_agent(
    settings: Settings,
    role: str,
    credential: Any,
    *,
    default_name: str,
    description: str | None = None,
) -> FoundryAgent:
    """Proxy to a specialist that is deployed as its own Foundry hosted agent."""
    toggle = settings.agents.toggle(role)
    return FoundryAgent(
        project_endpoint=settings.foundry.require_endpoint(),
        agent_name=toggle.hosted_name or default_name,
        agent_version=toggle.hosted_version or None,
        credential=credential,
        name=toggle.hosted_name or default_name,
        description=description,
    )
