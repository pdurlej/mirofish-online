import pytest

from app.utils.llm_client import LLMClient


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
