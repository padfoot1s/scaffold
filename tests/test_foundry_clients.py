"""Client selection per model role. Constructing clients makes no network calls."""

from agent_framework.foundry import AnthropicFoundryClient, FoundryChatClient
from azure.identity.aio import AzureCliCredential

from inswa.infra.foundry import create_chat_client, default_model_options
from tests.conftest import make_settings


async def test_openai_and_claude_roles_get_their_own_clients(tmp_path):
    settings = make_settings(
        tmp_path,
        foundry={
            "project_endpoint": "https://acct.services.ai.azure.com/api/projects/p",
            "default_model": "claude-reasoning",
            "default_provider": "anthropic",
            "models": {"router": "gpt-router"},
            "providers": {"router": "openai"},
        },
    )
    credential = AzureCliCredential()
    try:
        router = create_chat_client(settings, "router", credential)
        reasoning = create_chat_client(settings, "orchestrator", credential)
        assert isinstance(router, FoundryChatClient)
        assert isinstance(reasoning, AnthropicFoundryClient)
        assert reasoning.model == "claude-reasoning"
        assert str(reasoning.anthropic_client.base_url).startswith(
            "https://acct.services.ai.azure.com/anthropic"
        )
        assert default_model_options(settings, "orchestrator") == {"max_tokens": 4096}
        assert default_model_options(settings, "router") == {}
        await reasoning.close()
        await router.close()
    finally:
        await credential.close()
