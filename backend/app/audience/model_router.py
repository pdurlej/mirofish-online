"""Deterministic model routing for synthetic audience personas."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from .personas import AudiencePersona


DEFAULT_MODEL_POOL = (
    "gemma4:31b",
)
# Deliberately equal to the pool's only entry, which makes the rescue path a
# no-op out of the box: _should_high_quality_retry requires model != retry_model.
# Naming a specific second model here would assume every deployment can reach
# it, so the default stays honest and `high_quality_retry_available` in the
# receipt reports when nothing can be retried. Set
# MIROFISH_AUDIENCE_RETRY_MODEL to switch it on.
#
# Entry criteria for that variable, from the measured bake-offs: zero schema
# fallbacks across a batch and full reaction coverage. On 2026-07-08 only
# deepseek-v4-pro cleared both (12/12 green, 240/240 reactions, 0 fallbacks);
# gemma4:31b won the earlier bake-off and stays the default pool.
HIGH_QUALITY_RETRY_MODEL = "gemma4:31b"


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
        # Normalized like the pool entries. Without this a retry model given as
        # "deepseek-v4-pro:cloud" would never match a pool that had its suffix
        # stripped, and the mismatch would look like a working rescue path.
        self.high_quality_retry_model = _normalize_model_id(
            high_quality_retry_model
            or os.environ.get("MIROFISH_AUDIENCE_RETRY_MODEL")
            or HIGH_QUALITY_RETRY_MODEL
        )

    @property
    def high_quality_retry_available(self) -> bool:
        """Whether a failed persona can actually be retried on a different model."""
        return self.high_quality_retry_model not in self.model_pool

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

        persona_model_hint = _normalize_model_id(persona.model_hint)
        if persona_model_hint and persona_model_hint in self.model_pool:
            return ModelAssignment(
                persona_id=persona.id,
                model=persona_model_hint,
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
    values = tuple(_normalize_model_id(value.strip()) for value in raw.split(",") if value.strip())
    return values or DEFAULT_MODEL_POOL


def _normalize_model_id(model: str | None) -> str | None:
    if not model:
        return model
    return model.removesuffix(":cloud")
