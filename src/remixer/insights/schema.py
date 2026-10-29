"""A small JSON-schema subset for validating LLM output, stdlib only.

Supported keywords: ``type`` (string or list), ``properties``, ``required``,
``additionalProperties`` (bool), ``items``, ``enum``, ``minimum``, ``maximum``, ``minLength``,
``maxLength``, ``minItems``, ``maxItems``. Booleans are never numbers.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class LLMOutputError(ValueError):
    """The model's reply is not valid JSON or does not match the role's schema."""


def validate(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Problems with ``value`` (empty when valid)."""
    errors: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = [t] if isinstance(t, str) else list(t)
        if not any(_TYPES[x](value) for x in types):
            return [f"{path}: expected {'|'.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {list(schema['enum'])}")
    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > {schema['maximum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, v in enumerate(value):
                errors += validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errors += [f"{path}: missing {k}" for k in schema.get("required", ()) if k not in value]
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected {k}" for k in sorted(set(value) - set(props))]
        for k, sub in props.items():
            if k in value:
                errors += validate(value[k], sub, f"{path}.{k}")
    return errors


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_json_object(text: Any) -> dict:
    """The JSON object in a model reply; tolerates a code fence or text around one object."""
    if not isinstance(text, str):
        raise LLMOutputError(f"reply is {type(text).__name__}, not text")
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        a, b = body.find("{"), body.rfind("}")
        if a < 0 or b <= a:
            raise LLMOutputError("reply contains no JSON object") from None
        try:
            obj = json.loads(body[a:b + 1])
        except json.JSONDecodeError as e:
            raise LLMOutputError(f"invalid JSON: {e}") from None
    if not isinstance(obj, dict):
        raise LLMOutputError("reply is JSON but not an object")
    return obj
