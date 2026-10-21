from inswa.infra.feedback import FeedbackRecord, create_feedback_store
from inswa.infra.memory import create_memory_store
from inswa.infra.search import create_search_service
from inswa.infra.secrets import LocalSecretProvider, create_secret_provider
from tests.conftest import make_settings


async def test_local_memory_round_trip(tmp_path):
    store = await create_memory_store(make_settings(tmp_path))
    memory = await store.load("conv-1")
    memory.slots = {"sku": "123"}
    memory.pending_intents = ["forecast"]
    await store.save(memory)
    reloaded = await store.load("conv-1")
    assert reloaded.slots == {"sku": "123"}
    assert reloaded.pending_intents == ["forecast"]


async def test_local_feedback_round_trip(tmp_path):
    store = await create_feedback_store(make_settings(tmp_path))
    await store.add(FeedbackRecord(conversation_id="conv-1", rating=1, comment="useful"))
    await store.add(FeedbackRecord(conversation_id="conv-2", rating=-1))
    records = await store.for_conversation("conv-1")
    assert [r.comment for r in records] == ["useful"]


async def test_local_search_ranks_relevant_documents(tmp_path):
    search = await create_search_service(make_settings(tmp_path))
    hits = await search.search("variance actuals threshold", top_k=2)
    assert hits[0].id == "DOC-variance-policy"


async def test_local_secret_provider_normalizes_names(tmp_path):
    provider = create_secret_provider(make_settings(tmp_path, secrets={"mcp_api_key": "s3cret"}))
    assert isinstance(provider, LocalSecretProvider)
    assert await provider.get("mcp-api-key") == "s3cret"
    assert await provider.get("missing") is None
