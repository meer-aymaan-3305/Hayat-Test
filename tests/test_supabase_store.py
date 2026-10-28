from types import SimpleNamespace
from uuid import UUID

from pydantic import SecretStr
from postgrest.exceptions import APIError

from hayat_backend.config import Settings
from hayat_backend.supabase_store import SupabaseStore, create_store
from hayat_backend.memory_store import Conversation
from hayat_backend.schemas.intake import FactStatus, FactValue


class _InsertTable:
    def __init__(self, name: str, calls: list[tuple[str, str, object]]) -> None:
        self.name = name
        self.calls = calls

    def insert(self, payload):
        self.calls.append((self.name, "insert", payload))
        return self

    def execute(self):
        payload = self.calls[-1][2]
        return SimpleNamespace(data=[{**payload}])


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def table(self, name: str) -> _InsertTable:
        return _InsertTable(name, self.calls)


class _LegacyReadTable:
    def __init__(self, name: str) -> None:
        self.name = name
        self.selection = ""

    def select(self, selection):
        self.selection = selection
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self.name == "conversations" and self.selection == "state":
            raise APIError({"message": "column conversations.state does not exist", "code": "42703"})
        if self.name == "case_fact_versions":
            raise APIError({"message": 'relation "case_fact_versions" does not exist', "code": "42P01"})
        if self.name == "conversations":
            return SimpleNamespace(data={
                "id": "00000000-0000-0000-0000-000000000001",
                "guest_session_id": "00000000-0000-0000-0000-000000000002",
            })
        return SimpleNamespace(data=[])


class _LegacyClient:
    def table(self, name: str) -> _LegacyReadTable:
        return _LegacyReadTable(name)


class _LegacyStateWriteTable:
    def update(self, _payload):
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        raise APIError({
            "message": "Could not find the 'state' column of 'conversations' in the schema cache",
            "code": "PGRST204",
        })


class _LegacyStateWriteClient:
    def table(self, name: str) -> _LegacyStateWriteTable:
        return _LegacyStateWriteTable()


class _EmptyLeadTable:
    def select(self, _selection):
        return self

    def eq(self, *_args):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return None


class _EmptyLeadClient:
    def table(self, _name: str) -> _EmptyLeadTable:
        return _EmptyLeadTable()


class _LegacyConsentTable:
    def select(self, _selection):
        return self

    def eq(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        raise APIError({
            "message": "column consent_records.granted does not exist",
            "code": "42703",
        })


class _LegacyConsentClient:
    def table(self, _name: str):
        return _LegacyConsentTable()


class _FactTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.payload = None

    def select(self, _selection):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def maybe_single(self):
        return self

    def upsert(self, payload, on_conflict=None):
        self.client.upsert_conflict = on_conflict
        self.client.current = payload
        return self

    def insert(self, payload):
        self.client.history.append(payload)
        return self

    def execute(self):
        if self.name == "case_fact_versions" and self.client.history:
            return SimpleNamespace(data=self.client.history)
        if self.name == "case_fact_versions":
            return SimpleNamespace(data=[])
        if self.client.current:
            return SimpleNamespace(data={
                **self.client.current,
                "id": self.client.current.get(
                    "id", "00000000-0000-0000-0000-000000000003"
                ),
            })
        return SimpleNamespace(data=[])


class _FactClient:
    def __init__(self):
        self.current = None
        self.history = []
        self.upsert_conflict = None

    def table(self, name):
        return _FactTable(self, name)


def test_guest_session_persists_only_a_hash():
    client = _Client()
    session, raw_token = SupabaseStore(client).create_guest_session("ar")

    assert raw_token not in client.calls[0][2].values()
    assert client.calls[0][2]["token_hash"] == SupabaseStore.hash_token(raw_token)
    assert session.locale == "ar"


def test_factory_uses_memory_store_without_complete_supabase_settings():
    settings = Settings(app_env="test", supabase_url="https://example.supabase.co")

    store = create_store(settings)

    assert store.__class__.__name__ == "MemoryStore"


def test_legacy_schema_does_not_turn_chat_restore_into_a_500():
    store = SupabaseStore(_LegacyClient())
    conversation = store.get_conversation(
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert conversation.state == "requested"
    assert conversation.fact_history == []


def test_legacy_schema_state_write_does_not_turn_chat_into_a_500():
    store = SupabaseStore(_LegacyStateWriteClient())
    conversation = type(
        "ConversationStub",
        (),
        {"id": UUID("00000000-0000-0000-0000-000000000001"), "state": "requested"},
    )()

    store.set_conversation_state(conversation, "awaiting_details")

    assert conversation.state == "awaiting_details"


def test_missing_lead_is_treated_as_unverified():
    store = SupabaseStore(_EmptyLeadClient())

    assert store.lead_for(UUID("00000000-0000-0000-0000-000000000001")) is None


def test_legacy_consent_schema_does_not_turn_chat_into_a_500():
    store = SupabaseStore(_LegacyConsentClient())

    assert store.has_valid_consent(
        UUID("00000000-0000-0000-0000-000000000001"),
        "consultation_processing",
    ) is False


def test_case_facts_use_conversation_upsert_and_preserve_versions():
    client = _FactClient()
    store = SupabaseStore(client)
    conversation = Conversation(
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    )
    first = FactValue(
        field_name="destination_preference", value="India",
        status=FactStatus.CONFIRMED,
    )
    second = FactValue(
        field_name="destination_preference", value="Oman",
        status=FactStatus.CONFIRMED,
    )

    store.save_fact_updates(conversation, [first])
    store.save_fact_updates(conversation, [second])

    assert client.upsert_conflict == "conversation_id"
    assert client.current["facts"]["destination_preference"] == "Oman"
    assert len(client.history) == 2
    assert client.history[0]["facts"][0]["value"] == "India"
