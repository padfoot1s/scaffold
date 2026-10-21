"""Microsoft Foundry connections: credentials, per-role chat clients and remote hosted agents.

There is intentionally no local stand-in for Foundry models.
"""

from __future__ import annotations

from typing import Any

from agent_framework.foundry import FoundryAgent, FoundryChatClient
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential

from inswa.config import Settings


def create_credential(settings: Settings) -> Any:
    """Async Azure credential shared by Foundry, Cosmos, AI Search and Key Vault clients."""
    client_id = settings.azure.managed_identity_client_id or None
    match settings.azure.credential:
        case "cli":
            return AzureCliCredential()
        case "managed_identity":
            return ManagedIdentityCredential(client_id=client_id)
        case _:
            return DefaultAzureCredential(managed_identity_client_id=client_id)


def create_chat_client(settings: Settings, role: str, credential: Any) -> FoundryChatClient:
    """Foundry Responses client bound to the model deployment configured for `role`."""
    return FoundryChatClient(
        project_endpoint=settings.foundry.require_endpoint(),
        model=settings.foundry.model_for(role),
        credential=credential,
    )


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
