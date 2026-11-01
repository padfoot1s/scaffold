"""Grounding search: local keyword search over a JSON corpus, or Azure AI Search."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from inswa.config import Settings
from inswa.infra.secrets import SecretProvider


class SearchHit(BaseModel):
    id: str
    title: str
    content: str
    score: float


class SearchService(Protocol):
    async def search(self, query: str, top_k: int) -> list[SearchHit]: ...

    async def aclose(self) -> None: ...


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


class LocalSearchService:
    def __init__(self, corpus_path: Path) -> None:
        self._docs: list[dict[str, Any]] = (
            json.loads(corpus_path.read_text(encoding="utf-8")) if corpus_path.exists() else []
        )

    async def search(self, query: str, top_k: int) -> list[SearchHit]:
        terms = _tokens(query)
        hits = []
        for doc in self._docs:
            doc_terms = _tokens(f"{doc['title']} {doc['content']} {' '.join(doc.get('tags', []))}")
            score = len(terms & doc_terms)
            if score:
                hits.append(SearchHit(id=doc["id"], title=doc["title"], content=doc["content"], score=score))
        return sorted(hits, key=lambda h: h.score, reverse=True)[:top_k]

    async def aclose(self) -> None:
        pass


class AzureSearchService:
    def __init__(self, endpoint: str, index: str, credential: Any) -> None:
        from azure.search.documents.aio import SearchClient

        self._client = SearchClient(endpoint=endpoint, index_name=index, credential=credential)

    async def search(self, query: str, top_k: int) -> list[SearchHit]:
        results = await self._client.search(search_text=query, top=top_k)
        return [
            SearchHit(
                id=str(r["id"]),
                title=r.get("title", ""),
                content=r.get("content", ""),
                score=r.get("@search.score", 0.0),
            )
            async for r in results
        ]

    async def aclose(self) -> None:
        await self._client.close()


async def create_search_service(
    settings: Settings, *, credential: Any = None, secrets: SecretProvider | None = None
) -> SearchService:
    cfg = settings.search
    if cfg.provider == "azure":
        if not cfg.endpoint:
            raise ValueError("SEARCH__ENDPOINT must be set when SEARCH__PROVIDER=azure.")
        auth = credential
        if cfg.api_key_secret and secrets is not None:
            from azure.core.credentials import AzureKeyCredential

            key = await secrets.get(cfg.api_key_secret)
            auth = AzureKeyCredential(key) if key else credential
        return AzureSearchService(cfg.endpoint, cfg.index, auth)
    return LocalSearchService(cfg.local_corpus)
