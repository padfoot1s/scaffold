"""Secret resolution: local stand-in (SECRETS__* entries in .env) or Azure Key Vault."""

from __future__ import annotations

from typing import Any, Protocol

from inswa.config import Settings


class SecretProvider(Protocol):
    async def get(self, name: str) -> str | None: ...

    async def aclose(self) -> None: ...


def _normalize(name: str) -> str:
    return name.strip().lower().replace("-", "_")


class LocalSecretProvider:
    """Resolves secret names from `SECRETS__<NAME>` settings (Key Vault names may use dashes)."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = {_normalize(k): v for k, v in secrets.items()}

    async def get(self, name: str) -> str | None:
        return self._secrets.get(_normalize(name))

    async def aclose(self) -> None:
        pass


class KeyVaultSecretProvider:
    def __init__(self, vault_url: str, credential: Any) -> None:
        from azure.keyvault.secrets.aio import SecretClient

        self._client = SecretClient(vault_url=vault_url, credential=credential)
        self._cache: dict[str, str | None] = {}

    async def get(self, name: str) -> str | None:
        if name not in self._cache:
            from azure.core.exceptions import ResourceNotFoundError

            try:
                self._cache[name] = (await self._client.get_secret(name)).value
            except ResourceNotFoundError:
                self._cache[name] = None
        return self._cache[name]

    async def aclose(self) -> None:
        await self._client.close()


def create_secret_provider(settings: Settings, credential: Any = None) -> SecretProvider:
    if settings.keyvault.provider == "keyvault":
        if not settings.keyvault.url:
            raise ValueError("KEYVAULT__URL must be set when KEYVAULT__PROVIDER=keyvault.")
        return KeyVaultSecretProvider(settings.keyvault.url, credential)
    return LocalSecretProvider(settings.secrets)
