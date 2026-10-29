"""Cost control around every LLM call: input-hash cache, per-day budget, counters (decision 0021).

The statistical detector, the 3-listen gate, suppression and the deterministic confound rules all
run before this layer, so only surviving windows cost a call. Windows of one track share one call
per role.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from .llm import LLMClient, build_prompt, canonical, model_id


def cache_key(role: str, model: str, system: str, request: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({"role": role, "model": model, "system": system,
                                     "request": request}).encode()).hexdigest()


@dataclass
class ResponseCache:
    entries: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        return self.entries.get(key)

    def put(self, key: str, reply: str) -> None:
        self.entries[key] = reply


@dataclass
class CallBudget:
    per_day: int = 30
    used: dict[str, int] = field(default_factory=dict)

    def remaining(self, day: str) -> int:
        return max(0, self.per_day - self.used.get(day, 0))

    def spend(self, day: str) -> None:
        self.used[day] = self.used.get(day, 0) + 1


@dataclass
class CallStats:
    calls: int = 0
    cache_hits: int = 0
    denied: int = 0
    errors: int = 0
    invalid: int = 0
    fallbacks: int = 0
    windows_sent: int = 0
    by_role: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__, by_role=dict(self.by_role))


class BudgetExhausted(RuntimeError):
    pass


@dataclass
class Caller:
    """One night's access to the model: cache first, then budget, then the call itself."""
    llm: LLMClient
    cache: ResponseCache
    budget: CallBudget
    day: str
    stats: CallStats = field(default_factory=CallStats)

    def call(self, role: str, system: str, instructions: str, request: Mapping[str, Any]) -> str:
        """The raw reply. Raises ``BudgetExhausted``, or whatever the client raises."""
        key = cache_key(role, model_id(self.llm), system, request)
        hit = self.cache.get(key)
        if hit is not None:
            self.stats.cache_hits += 1
            return hit
        if self.budget.remaining(self.day) <= 0:
            self.stats.denied += 1
            raise BudgetExhausted(f"daily LLM budget of {self.budget.per_day} calls used")
        self.budget.spend(self.day)
        self.stats.calls += 1
        self.stats.by_role[role] = self.stats.by_role.get(role, 0) + 1
        self.stats.windows_sent += len(request.get("items", ()))
        return self.llm.complete(build_prompt(instructions, request), system=system,
                                 temperature=0, response_format="json")

    def remember(self, role: str, system: str, request: Mapping[str, Any], reply: str) -> None:
        """Cache a reply once it has passed validation; invalid replies are never cached."""
        self.cache.put(cache_key(role, model_id(self.llm), system, request), reply)
