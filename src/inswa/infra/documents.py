"""Document storage used for conversation memory and feedback.

`local` writes one JSON file per document under COSMOS__LOCAL_PATH/<container>/.
`cosmos` uses Azure Cosmos DB with Entra ID auth only (key auth is disabled on the account).

Writes use optimistic concurrency: `upsert(doc, etag=...)` fails with `ConcurrentUpdateError`
when the stored document changed since it was read; `etag=None` creates a new document.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Protocol

from inswa.config import Settings

ETAG = "_etag"


class ConcurrentUpdateError(Exception):
    """The document was changed (or created) by another writer since it was read."""


class DocumentStore(Protocol):
    async def get(self, doc_id: str, partition_key: str) -> dict[str, Any] | None: ...

    async def upsert(self, doc: dict[str, Any], *, etag: str | None) -> str: ...

    async def query(
        self, field: str, value: str, *, partition_key: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = asyncio.Lock()

    def _path(self, doc_id: str) -> Path:
        return self._root / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', doc_id)}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    async def get(self, doc_id: str, partition_key: str) -> dict[str, Any] | None:
        return self._read(self._path(doc_id))

    async def upsert(self, doc: dict[str, Any], *, etag: str | None) -> str:
        async with self._lock:
            path = self._path(doc["id"])
            current = self._read(path)
            if (current.get(ETAG) if current else None) != etag:
                raise ConcurrentUpdateError(doc["id"])
            new_etag = uuid.uuid4().hex
            self._root.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({**doc, ETAG: new_etag}, indent=2, default=str), encoding="utf-8")
            return new_etag

    async def query(
        self, field: str, value: str, *, partition_key: str | None = None
    ) -> list[dict[str, Any]]:
        if not self._root.exists():
            return []
        docs = (json.loads(p.read_text(encoding="utf-8")) for p in sorted(self._root.glob("*.json")))
        return [d for d in docs if d.get(field) == value]

    async def aclose(self) -> None:
        pass


class CosmosDocumentStore:
    def __init__(self, endpoint: str, database: str, container: str, credential: Any) -> None:
        from azure.cosmos.aio import CosmosClient

        self._client = CosmosClient(endpoint, credential=credential)
        self._container = self._client.get_database_client(database).get_container_client(container)

    async def get(self, doc_id: str, partition_key: str) -> dict[str, Any] | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return await self._container.read_item(item=doc_id, partition_key=partition_key)
        except CosmosResourceNotFoundError:
            return None

    async def upsert(self, doc: dict[str, Any], *, etag: str | None) -> str:
        from azure.core import MatchConditions
        from azure.cosmos.exceptions import (
            CosmosAccessConditionFailedError,
            CosmosResourceExistsError,
            CosmosResourceNotFoundError,
        )

        body = json.loads(json.dumps({k: v for k, v in doc.items() if k != ETAG}, default=str))
        try:
            if etag is None:
                stored = await self._container.create_item(body)
            else:
                stored = await self._container.replace_item(
                    item=body["id"], body=body, etag=etag, match_condition=MatchConditions.IfNotModified
                )
        # Not found on replace: the document was deleted (e.g. TTL) after it was read. Treat it like
        # any other lost race so the caller reloads and recreates it.
        except (
            CosmosAccessConditionFailedError,
            CosmosResourceExistsError,
            CosmosResourceNotFoundError,
        ) as ex:
            raise ConcurrentUpdateError(body["id"]) from ex
        return stored[ETAG]

    async def query(
        self, field: str, value: str, *, partition_key: str | None = None
    ) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
            raise ValueError(f"Invalid field name '{field}'.")
        items = self._container.query_items(
            query=f"SELECT * FROM c WHERE c.{field} = @value",
            parameters=[{"name": "@value", "value": value}],
            partition_key=partition_key,
        )
        return [item async for item in items]

    async def aclose(self) -> None:
        await self._client.close()


def create_document_store(settings: Settings, container: str, *, credential: Any = None) -> DocumentStore:
    cfg = settings.cosmos
    if cfg.provider == "cosmos":
        if not cfg.endpoint:
            raise ValueError("COSMOS__ENDPOINT must be set when COSMOS__PROVIDER=cosmos.")
        return CosmosDocumentStore(cfg.endpoint, cfg.database, container, credential)
    return LocalDocumentStore(cfg.local_path / container)
