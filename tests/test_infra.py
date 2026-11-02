import pytest

from inswa.infra.documents import ConcurrentUpdateError, CosmosDocumentStore
from inswa.infra.feedback import FeedbackRecord, create_feedback_store
from inswa.infra.memory import create_memory_store, document_key
from inswa.infra.search import create_search_service
from tests.conftest import make_settings


class _StubContainer:
    """Stands in for the Cosmos container client: every call raises the configured SDK error."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def create_item(self, body):
        raise self._error

    async def replace_item(self, **kwargs):
        raise self._error

    async def read_item(self, **kwargs):
        raise self._error


def _cosmos_store(error: Exception) -> CosmosDocumentStore:
    store = object.__new__(CosmosDocumentStore)
    store._container = _StubContainer(error)
    return store


@pytest.mark.parametrize(
    ("error_name", "etag"),
    [
        ("CosmosResourceExistsError", None),  # create over an existing document (409)
        ("CosmosAccessConditionFailedError", "old"),  # stale ETag (412)
        ("CosmosResourceNotFoundError", "old"),  # deleted since it was read (404)
    ],
)
async def test_cosmos_write_conflicts_become_concurrent_update_errors(error_name, etag):
    from azure.cosmos import exceptions

    store = _cosmos_store(getattr(exceptions, error_name)(message="x"))
    with pytest.raises(ConcurrentUpdateError):
        await store.upsert({"id": "c1"}, etag=etag)


async def test_cosmos_get_returns_none_for_missing_document():
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    assert await _cosmos_store(CosmosResourceNotFoundError(message="x")).get("c1", "c1") is None


async def test_cosmos_other_errors_are_not_swallowed():
    from azure.cosmos.exceptions import CosmosHttpResponseError

    with pytest.raises(CosmosHttpResponseError):
        await _cosmos_store(CosmosHttpResponseError(status_code=403, message="x")).upsert(
            {"id": "c1"}, etag=None
        )


def test_document_key_is_cosmos_safe_injective_and_keeps_ordinary_ids():
    assert document_key("conv-1_a.b~c") == "conv-1_a.b~c"
    keys = {document_key(i) for i in ["a/b", "a%2Fb", "a#b", "a?b", "a\\b", "a b", "caf\u00e9"]}
    assert len(keys) == 7
    assert not any(set(k) & set("/\\?#") for k in keys)


@pytest.mark.parametrize("conversation_id", ["a/b", "a#b", "a?b", "a\\b", "a%2Fb", "caf\u00e9 1"])
async def test_memory_round_trips_ids_cosmos_would_reject(tmp_path, conversation_id):
    store = create_memory_store(make_settings(tmp_path))
    memory = await store.load(conversation_id)
    memory.slots = {"sku": "123"}
    await store.save(memory)
    reloaded = await store.load(conversation_id)
    assert reloaded.id == conversation_id
    assert reloaded.slots == {"sku": "123"}


async def test_distinct_conversation_ids_do_not_share_memory(tmp_path):
    store = create_memory_store(make_settings(tmp_path))
    first = await store.load("a/b")
    first.slots = {"sku": "1"}
    await store.save(first)
    assert (await store.load("a%2Fb")).slots == {}


async def test_local_memory_round_trip(tmp_path):
    store = create_memory_store(make_settings(tmp_path))
    memory = await store.load("conv-1")
    memory.slots = {"sku": "123"}
    memory.pending_intents = ["forecast"]
    await store.save(memory)
    reloaded = await store.load("conv-1")
    assert reloaded.slots == {"sku": "123"}
    assert reloaded.pending_intents == ["forecast"]


async def test_stale_memory_write_is_rejected(tmp_path):
    store = create_memory_store(make_settings(tmp_path))
    first, second = await store.load("conv-1"), await store.load("conv-1")
    await store.save(first)
    with pytest.raises(ConcurrentUpdateError):
        await store.save(second)


async def test_update_reapplies_change_on_latest_version(tmp_path):
    store = create_memory_store(make_settings(tmp_path))
    stale = await store.load("conv-1")
    fresh = await store.load("conv-1")
    fresh.slots = {"sku": "from-other-turn"}
    await store.save(fresh)

    await store.update(stale, lambda m: m.pending_intents.append("forecast"))
    latest = await store.load("conv-1")
    assert latest.slots == {"sku": "from-other-turn"}
    assert latest.pending_intents == ["forecast"]


async def test_local_feedback_round_trip(tmp_path):
    store = create_feedback_store(make_settings(tmp_path))
    await store.add(FeedbackRecord(conversation_id="conv-1", rating=1, comment="useful"))
    await store.add(FeedbackRecord(conversation_id="conv-2", rating=-1))
    records = await store.for_conversation("conv-1")
    assert [r.comment for r in records] == ["useful"]


async def test_local_search_ranks_relevant_documents(tmp_path):
    search = await create_search_service(make_settings(tmp_path))
    hits = await search.search("variance actuals threshold", top_k=2)
    assert hits[0].id == "DOC-variance-policy"


async def test_search_without_key_uses_the_entra_credential(tmp_path, monkeypatch):
    captured = _capture_search_auth(monkeypatch)
    entra = object()
    settings = make_settings(tmp_path, search={"provider": "azure", "endpoint": "https://s.example"})
    await create_search_service(settings, credential=entra)
    assert captured["auth"] is entra


@pytest.mark.parametrize("empty", [None, ""])
async def test_search_empty_key_falls_back_to_entra(tmp_path, monkeypatch, empty):
    captured = _capture_search_auth(monkeypatch)
    entra = object()
    settings = make_settings(
        tmp_path, search={"provider": "azure", "endpoint": "https://s.example", "api_key": empty}
    )
    await create_search_service(settings, credential=entra)
    assert captured["auth"] is entra


async def test_search_api_key_from_settings_is_used_and_masked(tmp_path, monkeypatch):
    from azure.core.credentials import AzureKeyCredential

    captured = _capture_search_auth(monkeypatch)
    settings = make_settings(
        tmp_path, search={"provider": "azure", "endpoint": "https://s.example", "api_key": "s3cret"}
    )
    await create_search_service(settings, credential=object())
    assert isinstance(captured["auth"], AzureKeyCredential)
    assert captured["auth"].key == "s3cret"
    assert "s3cret" not in repr(settings)


def _capture_search_auth(monkeypatch) -> dict:
    captured: dict = {}

    class FakeAzureSearch:
        def __init__(self, endpoint, index, auth):
            captured["auth"] = auth

    monkeypatch.setattr("inswa.infra.search.AzureSearchService", FakeAzureSearch)
    return captured
