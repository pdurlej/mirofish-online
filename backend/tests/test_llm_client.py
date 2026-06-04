import pytest

from app.utils.llm_client import LLMClient


class FakeUsage:
    def model_dump(self):
        return {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}


class FakeMessage:
    content = "<think>hidden</think>OK"


class FakeChoice:
    message = FakeMessage()
    finish_reason = "stop"


class FakeResponse:
    model = "deepseek-v4-flash"
    choices = [FakeChoice()]
    usage = FakeUsage()


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeResponse()


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = FakeChat()


def test_chat_with_metadata_returns_usage_and_sanitized_content():
    client = object.__new__(LLMClient)
    client.client = FakeOpenAIClient()
    client.base_url = "https://ollama.example/v1"
    client.model = "default-model"
    client._num_ctx = 8192

    result = client.chat_with_metadata(messages=[], model="deepseek-v4-flash")

    assert result.content == "OK"
    assert result.model == "deepseek-v4-flash"
    assert result.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }
    assert result.finish_reason == "stop"


def test_chat_json_accepts_json_object_with_trailing_text():
    client = object.__new__(LLMClient)

    def fake_chat(**_kwargs):
        return '{"ok": true, "items": [1, 2]}\n\nExtra explanatory text.'

    client.chat = fake_chat

    assert client.chat_json(messages=[]) == {"ok": True, "items": [1, 2]}


def test_chat_json_error_does_not_include_raw_model_output():
    client = object.__new__(LLMClient)

    def fake_chat(**_kwargs):
        return '{"private": "do not leak", "items": ['

    client.chat = fake_chat

    with pytest.raises(ValueError) as exc_info:
        client.chat_json(messages=[])

    message = str(exc_info.value)
    assert "Invalid JSON format from LLM" in message
    assert "chars=" in message
    assert "do not leak" not in message
    assert '{"private"' not in message


def test_chat_schema_accepts_valid_json(monkeypatch):
    monkeypatch.setattr("app.utils.llm_client.Config.MIROFISH_JSON_MODEL", "schema-model")
    client = object.__new__(LLMClient)
    seen = {}

    def fake_chat(**kwargs):
        seen.update(kwargs)
        return '{"ok": true, "items": ["one", "two"]}'

    client.chat = fake_chat
    client.model = "default-model"

    schema = {
        "type": "object",
        "required": ["ok", "items"],
        "properties": {
            "ok": {"type": "boolean"},
            "items": {"type": "array", "minItems": 2, "items": {"type": "string"}},
        },
    }

    assert client.chat_schema("json", schema, messages=[]) == {
        "ok": True,
        "items": ["one", "two"],
    }
    assert seen["model"] == "schema-model"
    assert seen["response_format"]["type"] == "json_schema"


def test_chat_schema_passes_reasoning_effort(monkeypatch):
    monkeypatch.setattr("app.utils.llm_client.Config.MIROFISH_JSON_MODEL", "schema-model")
    client = object.__new__(LLMClient)
    seen = {}

    def fake_chat(**kwargs):
        seen.update(kwargs)
        return '{"ok": true}'

    client.chat = fake_chat
    client.model = "default-model"
    schema = {
        "type": "object",
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }

    assert client.chat_schema(
        "json",
        schema,
        messages=[],
        reasoning_effort="medium",
    ) == {"ok": True}
    assert seen["reasoning_effort"] == "medium"


def test_chat_schema_falls_back_when_provider_rejects_json_schema():
    client = object.__new__(LLMClient)
    client.model = "fallback-model"
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        if kwargs.get("response_format", {}).get("type") == "json_schema":
            raise RuntimeError("unsupported response_format json_schema")
        return '{"ok": true}'

    client.chat = fake_chat
    schema = {
        "type": "object",
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }

    assert client.chat_schema("json", schema, messages=[]) == {"ok": True}
    assert len(calls) == 2
    assert calls[1]["response_format"] == {"type": "json_object"}


def test_chat_schema_falls_back_when_provider_ignores_schema():
    client = object.__new__(LLMClient)
    client.model = "fallback-model"
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return "{}"
        return '{"ok": true}'

    client.chat = fake_chat
    schema = {
        "type": "object",
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }

    assert client.chat_schema("json", schema, messages=[]) == {"ok": True}
    assert len(calls) == 2
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"] == {"type": "json_object"}


def test_chat_schema_error_does_not_include_raw_model_output():
    client = object.__new__(LLMClient)
    client.model = "safe-model"

    def fake_chat(**_kwargs):
        return '{"private": "do not leak", "items": []}'

    client.chat = fake_chat
    schema = {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {"type": "array", "minItems": 2, "items": {"type": "string"}},
        },
    }

    with pytest.raises(ValueError) as exc_info:
        client.chat_schema("json", schema, messages=[])

    message = str(exc_info.value)
    assert "Schema validation failed" in message
    assert "$.items" in message
    assert "do not leak" not in message
    assert "private" not in message
