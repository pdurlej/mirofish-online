"""Deterministic model routing for synthetic audience personas."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from .personas import AudiencePersona


DEFAULT_MODEL_POOL = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.1:cloud",
    "kimi-k2.6:cloud",
    "qwen3.5:cloud",
)
HIGH_QUALITY_RETRY_MODEL = "qwen3.5:397b-cloud"


@dataclass(frozen=True)
class ModelAssignment:
    persona_id: str
    model: str
    seed: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "persona_id": self.persona_id,
            "model": self.model,
            "seed": self.seed,
            "reason": self.reason,
        }


class ModelRouter:
    def __init__(
        self,
        model_pool: tuple[str, ...] | None = None,
        high_quality_retry_model: str | None = None,
    ) -> None:
        self.model_pool = model_pool or _model_pool_from_env()
        self.high_quality_retry_model = (
            high_quality_retry_model
            or os.environ.get("MIROFISH_AUDIENCE_RETRY_MODEL")
            or HIGH_QUALITY_RETRY_MODEL
        )

    def assign(
        self,
        persona: AudiencePersona,
        run_seed: str,
        run_id: str,
        *,
        high_quality_retry: bool = False,
    ) -> ModelAssignment:
        seed = f"{run_seed}:{run_id}:{persona.id}"
        if high_quality_retry:
            return ModelAssignment(
                persona_id=persona.id,
                model=self.high_quality_retry_model,
                seed=seed,
                reason="high_quality_retry",
            )

        if persona.model_hint and persona.model_hint in self.model_pool:
            return ModelAssignment(
                persona_id=persona.id,
                model=persona.model_hint,
                seed=seed,
                reason="persona_hint",
            )

        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % len(self.model_pool)
        return ModelAssignment(
            persona_id=persona.id,
            model=self.model_pool[index],
            seed=seed,
            reason="seeded_pool",
        )


def _model_pool_from_env() -> tuple[str, ...]:
    raw = os.environ.get("MIROFISH_AUDIENCE_MODEL_POOL")
    if not raw:
        return DEFAULT_MODEL_POOL
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    return values or DEFAULT_MODEL_POOL
