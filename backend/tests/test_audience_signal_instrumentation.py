"""The receipt has to show when the fallback wrote the answer instead of the model.

Production measurement that motivated this: 95.3% of 2223 live persona reactions
were stored as "curious" and 93.8% of objections as "medium", while a control
group written by a different pipeline had a spread across five stances. Nothing
in the receipt could tell whether the model really answered that way or whether
the loose normalizer substituted the values, because no counter existed.
"""

from __future__ import annotations

import json

from app.audience import AudienceLiveRunner, AudienceRunInput
from app.audience.channel_fit import CHANNELS
from app.audience.live_runner import (
    SEVERITY_VALUES,
    STANCE_VALUES,
    _normalize_stance,
    _parse_and_validate,
    _value_distribution,
)
from app.utils.llm_client import LLMChatResult


def _reaction(**overrides) -> str:
    payload = {
        "stance": "skeptical",
        "channel_fit": "fits a written post better than audio",
        "channel_scores": {channel: 50 for channel in CHANNELS},
        "summary": "The premise is plausible but the proof is missing.",
        "objection": "No evidence that the audience already wants this.",
        "objection_severity": "high",
        "insight": "Lead with the measurement, not the promise.",
        "decision_impact": "Would rewrite the opening before publishing.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_clean_response_reports_no_normalization():
    normalization: dict[str, bool] = {}
    parsed = _parse_and_validate(_reaction(), normalization=normalization)

    assert parsed["stance"] == "skeptical"
    assert parsed["objection_severity"] == "high"
    assert normalization == {}


def test_polish_stance_is_understood_rather_than_flattened():
    """The core regression. "sceptyczny" holds no "skeptic": Polish spells it
    with a c, so every Polish stance used to collapse into "curious"."""
    normalization: dict[str, bool] = {}
    parsed = _parse_and_validate(
        _reaction(stance="Sceptyczny, bo brak dowodu", objection_severity="wysoka"),
        normalization=normalization,
    )

    assert parsed["stance"] == "skeptical"
    assert parsed["objection_severity"] == "high"
    # The loose path still ran, but nothing had to be guessed.
    assert normalization["loose"] is True
    assert normalization["stance_unrecognized"] is False
    assert normalization["severity_unrecognized"] is False


def test_opaque_stance_is_reported_as_substituted():
    """When nothing matches, the fallback still picks, but now it says so."""
    normalization: dict[str, bool] = {}
    parsed = _parse_and_validate(_reaction(stance="n/a"), normalization=normalization)

    assert parsed["stance"] in STANCE_VALUES
    assert normalization["loose"] is True
    assert normalization["stance_unrecognized"] is True


def test_unrelated_field_error_does_not_count_as_an_invented_stance():
    """The distinction the whole diagnosis depends on.

    `_normalize_loose_response` rewrites the entire object, so a too-short
    summary drags a perfectly good stance through substitution. The run must
    report that normalization happened without claiming the stance was invented.
    """
    normalization: dict[str, bool] = {}
    parsed = _parse_and_validate(_reaction(summary="too short"), normalization=normalization)

    assert normalization["loose"] is True
    assert normalization["stance_unrecognized"] is False
    assert normalization["severity_unrecognized"] is False
    assert parsed["stance"] == "skeptical"
    assert parsed["objection_severity"] == "high"


def test_needs_translation_survives_the_loose_path():
    """Regression: "translate" is not a substring of "needs_translation".

    A persona answering `needs_translation` correctly used to be rewritten as
    `curious` whenever any other field sent the response down the loose path.
    Production held zero `needs_translation` across 2223 reactions.
    """
    assert _normalize_stance("needs_translation") == "needs_translation"

    normalization: dict[str, bool] = {}
    parsed = _parse_and_validate(
        _reaction(stance="needs_translation", summary="too short"),
        normalization=normalization,
    )

    assert parsed["stance"] == "needs_translation"
    assert normalization["stance_unrecognized"] is False


def test_enum_constants_track_the_schema():
    assert STANCE_VALUES == {"interested", "curious", "skeptical", "needs_translation"}
    assert SEVERITY_VALUES == {"low", "medium", "high"}


def test_value_distribution_orders_by_frequency():
    assert _value_distribution(["curious", "curious", "skeptical"]) == {
        "curious": 2,
        "skeptical": 1,
    }
    assert _value_distribution([]) == {}


class _ScriptedClient:
    """Answers every persona with the same fixed reaction body."""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat_with_metadata(self, **kwargs):
        return LLMChatResult(
            content=self._content,
            model=kwargs["model"],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            latency_ms=1,
            finish_reason="stop",
        )


class _CyclingStanceClient:
    """Answers with a different valid stance per call, in a fixed order."""

    _STANCES = ("interested", "curious", "skeptical", "needs_translation")

    def __init__(self) -> None:
        self._calls = 0

    def chat_with_metadata(self, **kwargs):
        stance = self._STANCES[self._calls % len(self._STANCES)]
        self._calls += 1
        return LLMChatResult(
            content=_reaction(stance=stance, objection=f"Objection {self._calls}."),
            model=kwargs["model"],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            latency_ms=1,
            finish_reason="stop",
        )


def test_polish_answers_no_longer_collapse_into_curious():
    """End-to-end: the exact input that produced the production distribution.

    A model told to write Polish values answers "Sceptyczny"/"wysoka". That used
    to be stored as curious/medium for all twenty personas, which is how 113 live
    runs ended up 95.3% curious. The stance now survives.
    """
    scripted = _ScriptedClient(_reaction(stance="Sceptyczny", objection_severity="wysoka"))
    result = AudienceLiveRunner(client_factory=lambda: scripted).run(
        AudienceRunInput(topic="Czy warto testować pomysły przed publikacją?", run_seed="pl")
    )
    receipt = result.to_dict()["receipt"]

    assert receipt["stance_distribution"] == {"skeptical": 20}
    assert receipt["severity_distribution"] == {"high": 20}
    assert receipt["unrecognized_stance_count"] == 0
    assert receipt["unrecognized_severity_count"] == 0
    # The loose path still ran, and the receipt still admits it.
    assert receipt["loose_normalization_count"] == 20


def test_uniform_panel_is_not_allowed_to_stay_green():
    """A panel that agrees with itself cannot separate this topic from any other.

    Production held 76 runs where all twenty personas shared one stance, every
    one graded green, because nothing looked at the spread.
    """
    scripted = _ScriptedClient(_reaction(stance="n/a"))
    result = AudienceLiveRunner(client_factory=lambda: scripted).run(
        AudienceRunInput(topic="Uniform panel probe", run_seed="flat")
    )
    receipt = result.to_dict()["receipt"]
    kinds = {warning["kind"] for warning in receipt["quality_warnings"]}

    assert len(receipt["stance_distribution"]) == 1
    assert "flat_stance_signal" in kinds
    assert "substituted_stances" in kinds
    assert receipt["unrecognized_stance_count"] == 20
    assert receipt["reliability_grade"] == "red"


def test_run_receipt_stays_quiet_when_the_model_answers_in_enum():
    """The counters must not cry wolf on a healthy run."""
    result = AudienceLiveRunner(client_factory=_CyclingStanceClient).run(
        AudienceRunInput(topic="Do product teams need audience rehearsal?", run_seed="en")
    )
    receipt = result.to_dict()["receipt"]

    assert receipt["loose_normalization_count"] == 0
    assert receipt["unrecognized_stance_count"] == 0
    assert receipt["unrecognized_severity_count"] == 0
    assert sum(receipt["stance_distribution"].values()) == 20
    assert len(receipt["stance_distribution"]) == 4
    assert receipt["severity_distribution"] == {"high": 20}
