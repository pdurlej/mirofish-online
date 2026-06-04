"""OpenAI-compatible model inventory helpers."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ModelInventory:
    models: list[str]

    def triage(self) -> dict[str, list[str]]:
        return {
            "primary": [
                model
                for model in self.models
                if model == "deepseek-v4-flash"
            ],
            "quality_retry": [model for model in self.models if model == "deepseek-v4-pro"],
            "candidate_review": [
                model
                for model in self.models
                if model
                in {
                    "glm-5.1",
                    "kimi-k2.6",
                    "minimax-m3",
                    "qwen3.5:397b",
                    "mistral-large-3:675b",
                    "nemotron-3-ultra",
                    "minimax-m2.7",
                    "deepseek-v3.2",
                }
            ],
        }


def list_openai_compatible_models(
    base_url: str,
    api_key: str,
    *,
    urlopen: Callable[..., Any] | None = None,
) -> ModelInventory:
    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": "Bearer " + api_key},
    )
    with opener(req, timeout=30) as response:
        payload = json.loads(response.read().decode())
    models = sorted(
        item["id"]
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    )
    return ModelInventory(models=models)
