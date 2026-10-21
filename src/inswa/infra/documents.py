"""Document storage used for conversation memory and feedback.

`local` writes one JSON file per document under COSMOS__LOCAL_PATH/<container>/.
`cosmos` uses Azure Cosmos DB (containers partitioned on `/id`).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Protocol

from inswa.config import Settings
from inswa.infra.secrets import SecretProvider


class DocumentStore(Protocol):
    async def get(self, doc_id: str) -> dict[str, Any] | None: ...

    async def upsert(self, doc: dict[str, Any]) -> None: ...

    async def query(self, field: str, value: str) -> list[dict[str, Any]]: ...


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = asyncio.Lock()

    def _path(self, doc_id: str) -> Path:
        return self._root / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', doc_id)}.json"

    async def get(self, doc_id: str) -> dict[str, Any] | None:
        path = self._path(doc_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    async def upsert(self, doc: dict[str, Any]) -> None:
        async with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            self._path(doc["id"]).write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")

    async def query(self, field: str, value: str) -> list[dict[str, Any]]:
        if not self._root.exists():
            return []
        docs = (json.loads(p.read_text(encoding="utf-8")) for p in sorted(self._root.glob("*.json")))
        return [d for d in docs if d.get(field) == value]


class CosmosDocumentStore:
    def __init__(self, endpoint: str, database: str, container: str, credential: Any) -> None:
        from azure.cosmos.aio import CosmosClient

        self._client = CosmosClient(endpoint, credential=credential)
        self._container = self._client.get_database_client(database).get_container_client(container)

    async def get(self, doc_id: str) -> dict[str, Any] | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return await self._container.read_item(item=doc_id, partition_key=doc_id)
        except CosmosResourceNotFoundError:
            return None

    async def upsert(self, doc: dict[str, Any]) -> None:
        await self._container.upsert_item(json.loads(json.dumps(doc, default=str)))

    async def query(self, field: str, value: str) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
            raise ValueError(f"Invalid field name '{field}'.")
        items = self._container.query_items(
            query=f"SELECT * FROM c WHERE c.{field} = @value",
            parameters=[{"name": "@value", "value": value}],
        )
        return [item async for item in items]


async def create_document_store(
    settings: Settings, container: str, *, credential: Any = None, secrets: SecretProvider | None = None
) -> DocumentStore:
    cfg = settings.cosmos
    if cfg.provider == "cosmos":
        if not cfg.endpoint:
            raise ValueError("COSMOS__ENDPOINT must be set when COSMOS__PROVIDER=cosmos.")
        auth = credential
        if cfg.key_secret and secrets is not None:
            auth = await secrets.get(cfg.key_secret) or credential
        return CosmosDocumentStore(cfg.endpoint, cfg.database, container, auth)
    return LocalDocumentStore(cfg.local_path / container)
