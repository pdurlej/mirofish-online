"""Versioned synthetic audience personas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTIVE_PERSONA_COUNT = 20
REQUIRED_SEGMENTS = {
    "produkt-w-praktyce",
    "linkedin",
    "blog",
    "twitter-x",
    "product-managers",
    "ai-platform-devtools",
    "solo-operators",
    "enterprise-governance",
    "skeptical-generalists",
}


@dataclass(frozen=True)
class AudiencePersona:
    id: str
    name: str
    active: bool
    segments: tuple[str, ...]
    goals: tuple[str, ...]
    objections: tuple[str, ...]
    channel_preferences: tuple[str, ...]
    skepticism: float
    model_hint: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AudiencePersona":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            active=bool(data.get("active", True)),
            segments=tuple(str(value) for value in data.get("segments", [])),
            goals=tuple(str(value) for value in data.get("goals", [])),
            objections=tuple(str(value) for value in data.get("objections", [])),
            channel_preferences=tuple(
                str(value) for value in data.get("channel_preferences", [])
            ),
            skepticism=float(data.get("skepticism", 0.5)),
            model_hint=data.get("model_hint"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "active": self.active,
            "segments": list(self.segments),
            "goals": list(self.goals),
            "objections": list(self.objections),
            "channel_preferences": list(self.channel_preferences),
            "skepticism": self.skepticism,
            "model_hint": self.model_hint,
        }


def load_default_personas() -> list[AudiencePersona]:
    path = Path(__file__).with_name("personas_v1.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    personas = [AudiencePersona.from_dict(item) for item in raw]
    validate_personas(personas)
    return personas


def validate_personas(personas: list[AudiencePersona]) -> None:
    active = [persona for persona in personas if persona.active]
    if len(active) != ACTIVE_PERSONA_COUNT:
        raise ValueError(
            f"Expected {ACTIVE_PERSONA_COUNT} active personas, got {len(active)}"
        )

    ids = [persona.id for persona in active]
    if len(ids) != len(set(ids)):
        raise ValueError("Persona ids must be unique")

    invalid = [
        persona.id
        for persona in active
        if not persona.segments
        or not persona.goals
        or not persona.objections
        or not persona.channel_preferences
        or not 0 <= persona.skepticism <= 1
    ]
    if invalid:
        raise ValueError(f"Invalid active personas: {', '.join(invalid)}")

    covered = {segment for persona in active for segment in persona.segments}
    missing = sorted(REQUIRED_SEGMENTS - covered)
    if missing:
        raise ValueError(f"Missing required audience segments: {', '.join(missing)}")
