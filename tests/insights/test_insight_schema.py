"""LLM replies are validated; malformed output is rejected, never trusted."""
import pytest

from remixer.insights.roles import ANALYST_SCHEMA, NARRATOR_SCHEMA, SKEPTIC_SCHEMA
from remixer.insights.schema import LLMOutputError, parse_json_object, validate


def test_schema_accepts_a_complete_analyst_item():
    item = {"window_id": "a:v1:0-5000", "hypothesis": "The drop is harsh.", "cause": "loudness_jump",
            "confidence": 0.8}
    assert validate({"items": [item]}, ANALYST_SCHEMA) == []


@pytest.mark.parametrize("item", [
    {"window_id": "a", "hypothesis": "x", "cause": "vibes", "confidence": 0.5},
    {"window_id": "a", "hypothesis": "x", "cause": "unknown", "confidence": 1.5},
    {"window_id": "a", "hypothesis": "", "cause": "unknown", "confidence": 0.5},
    {"hypothesis": "x", "cause": "unknown", "confidence": 0.5},
    {"window_id": "a", "hypothesis": "x", "cause": "unknown", "confidence": True},
])
def test_schema_rejects_bad_analyst_items(item):
    assert validate({"items": [item]}, ANALYST_SCHEMA)


def test_skeptic_requires_an_explicit_reason():
    bare = {"window_id": "a", "verdict": "reject", "confidence": 0.2, "reasons": []}
    assert validate({"items": [bare]}, SKEPTIC_SCHEMA)
    ok = {"window_id": "a", "verdict": "reject", "confidence": 0.2,
          "reasons": [{"code": "shuffle", "detail": "only in shuffle"}]}
    assert validate({"items": [ok]}, SKEPTIC_SCHEMA) == []


def test_narrator_bounds_the_sentence():
    assert validate({"items": [{"window_id": "a", "sentence": "too"}]}, NARRATOR_SCHEMA)
    assert validate({"items": [{"window_id": "a", "sentence": "x" * 200}]}, NARRATOR_SCHEMA)
    assert validate({"items": [{"window_id": "a", "sentence": "You've skipped 0:20-0:25."}]}, NARRATOR_SCHEMA) == []


@pytest.mark.parametrize("text", ["", "sure, skip it", "[1, 2]", "null", "{\"items\": [", "   "])
def test_parse_rejects_non_objects(text):
    with pytest.raises(LLMOutputError):
        parse_json_object(text)


def test_parse_tolerates_a_fence_and_prose_around_one_object():
    assert parse_json_object('```json\n{"items": []}\n```') == {"items": []}
    assert parse_json_object('Here you go: {"a": 1} thanks') == {"a": 1}


def test_parse_rejects_non_text():
    with pytest.raises(LLMOutputError):
        parse_json_object({"items": []})
