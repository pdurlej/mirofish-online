from __future__ import annotations

import json

from app.audience.model_inventory import list_openai_compatible_models


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "data": [
                    {"id": "deepseek-v4-pro"},
                    {"id": "glm-5.1"},
                    {"id": "qwen3.5:397b"},
                    {"id": "mistral-large-3:675b"},
                ]
            }
        ).encode()


def test_model_inventory_triages_cloud_models_without_secret_output():
    seen = {}

    def fake_urlopen(request, timeout):
        seen["auth"] = request.headers.get("Authorization")
        seen["timeout"] = timeout
        return FakeResponse()

    inventory = list_openai_compatible_models(
        "https://example.test/v1",
        "SECRET_TOKEN",
        urlopen=fake_urlopen,
    )

    assert inventory.models == [
        "deepseek-v4-pro",
        "glm-5.1",
        "mistral-large-3:675b",
        "qwen3.5:397b",
    ]
    assert inventory.triage()["primary"] == ["deepseek-v4-pro", "glm-5.1"]
    assert inventory.triage()["quality_retry"] == ["qwen3.5:397b"]
    assert inventory.triage()["candidate_review"] == ["mistral-large-3:675b"]
    assert seen["auth"] == "Bearer SECRET_TOKEN"
