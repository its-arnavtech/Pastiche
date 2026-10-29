# 0020: Insight layer: what it assumes from the core

- Date: 2026-10-29
- Agent: cursor-2
- Tasks: T-027 (requests: T-028, T-029)

The insight layer (`src/remixer/insights/`) does not import the core's `LLMClient` and does not edit core, GPU, CPU, DSP or NPU code. It defines the same two methods itself, so an adapter written against either one works. Numbered 0020 because `dev` uses decisions through 0017 and the unmerged recipe-planner branch uses 0018 and 0019.

## LLMClient (`insights/llm.py`): T-028

```python
class LLMClient(Protocol):
    def complete(self, prompt: str, system: str | None = None, **kw) -> str: ...
    def available(self) -> bool: ...
```

`complete` receives one prompt. The request JSON follows the line `REQUEST:`. `kw` is `temperature=0` and `response_format="json"`. The reply must be one JSON object, optionally inside a code fence. Roles and schemas live in `insights/roles.py` (`ANALYST_SCHEMA`, `SKEPTIC_SCHEMA`, `NARRATOR_SCHEMA`). A local Ollama model should honour `response_format`. The layer never raises on a bad reply: it falls back. `available()` false means the nightly job skips the run.

## TrackFeatures (`insights/evidence.py`): T-029

```python
class TrackFeatures(Protocol):
    def window_features(self, track_id: str, track_version: str) -> Sequence[WindowFeatures] | None: ...

@dataclass(frozen=True)
class WindowFeatures:
    index: int
    loudness_lufs: float | None = None
    tempo_bpm: float | None = None
    section: str | None = None
    stems: frozenset[str] = frozenset()
```

One entry per 5-second window, from the catalog's analysis. `None` means the request carries no musical changes and the Analyst says so.

## Nightly job (`insights/pipeline.py`): T-029

```python
def run_nightly(events: Iterable[Event], state: InsightState, llm: LLMClient, now_ms: int,
                features: TrackFeatures | None = None, cfg: InsightConfig = DEFAULT_INSIGHTS
                ) -> tuple[InsightState, NightlyReport]: ...
```

Pure apart from the model calls. The job loads `InsightState.from_json`, calls this once per user per local night with events up to `now_ms`, and stores `state.to_json()`. It does not touch playback. The inbox reads `inbox_view(state)`.
