"""The LLM seam: a ``Protocol`` with the same shape as the core's ``LLMClient``, plus a scripted mock.

The insight layer never imports the core. Any object with ``complete`` and ``available`` works,
including the core's ``remixer.interfaces.LLMClient`` subclasses (an Ollama adapter is task T-028).

Every call sends one JSON request after ``REQUEST_MARKER`` and expects one JSON object back.
Calls pass ``temperature=0`` and ``response_format="json"`` as keyword hints that adapters may
ignore.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, runtime_checkable

REQUEST_MARKER = "REQUEST:"


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, prompt: str, system: str | None = None, **kw: Any) -> str: ...

    def available(self) -> bool: ...


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_prompt(instructions: str, request: Mapping[str, Any]) -> str:
    return f"{instructions}\n\n{REQUEST_MARKER}\n{canonical(request)}"


def read_request(prompt: str) -> dict:
    """The request object a prompt carries (used by mocks and tests)."""
    _, _, body = prompt.rpartition(REQUEST_MARKER)
    return json.loads(body)


def model_id(llm: Any) -> str:
    return str(getattr(llm, "model", None) or type(llm).__name__)


Script = Callable[[dict, "str | None"], Any]


class MockLLM:
    """Deterministic test double.

    ``script`` is either a callable ``(request, system) -> reply`` or a sequence of replies used in
    order (an exhausted sequence raises). A reply may be a string (returned as is), a dict (returned
    as JSON) or an exception instance (raised, to simulate a failing backend). Every request is
    recorded in ``calls``.
    """

    def __init__(self, script: Script | Sequence[Any], *, model: str = "mock-llm", up: bool = True):
        self.model = model
        self.up = up
        self.calls: list[dict] = []
        self._script = script if callable(script) else iter(list(script))

    def available(self) -> bool:
        return self.up

    def complete(self, prompt: str, system: str | None = None, **kw: Any) -> str:
        request = read_request(prompt)
        self.calls.append(request)
        if callable(self._script):
            reply = self._script(request, system)
        else:
            try:
                reply = next(self._script)
            except StopIteration:
                raise RuntimeError("MockLLM script exhausted") from None
        if isinstance(reply, BaseException):
            raise reply
        return reply if isinstance(reply, str) else canonical(reply)

    def roles(self) -> list[str]:
        return [c.get("role") for c in self.calls]


def by_role(**scripts: Script) -> Script:
    """Dispatch on ``request["role"]``; roles without a script get an empty item list."""
    def run(request: dict, system: str | None) -> Any:
        fn = scripts.get(request.get("role"))
        return fn(request, system) if fn else {"items": []}
    return run


def items_of(request: Mapping[str, Any]) -> Iterable[dict]:
    return request.get("items", [])
