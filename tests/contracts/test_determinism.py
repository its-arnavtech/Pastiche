"""Same inputs and seed give identical results whichever tenant or storage batching they went through.

The analytics and fatigue pipeline is run on events read back from the profile's EventSink, so a
profile that reorders, retypes or drops fields fails here (spec section 9: identical results
under both profiles).
"""
import random

from remixer.analytics.events import Event
from remixer.analytics.heatmap import build_heatmap
from remixer.analytics.interpret import interpret
from remixer.analytics.simulate import simulate
from remixer.fatigue.credit import StemUse
from remixer.fatigue.insights import insights_from_candidates
from remixer.fatigue.selection import StemCandidate, select_batch
from remixer.fatigue.state import replay

SIM = simulate(n_tracks=24, n_sessions=300, seed=21)


def store(adapters, batch: int, shuffle_seed: int | None) -> list[Event]:
    rows = [e.to_row() for e in SIM.events]
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(rows)
    for i in range(0, len(rows), batch):
        adapters.events.append("playback", rows[i:i + batch])
    return [Event.from_row(r) for r in adapters.events.read("playback")]


def recipes(track_id, version):
    n = sum(map(ord, track_id))
    return [StemUse(f"stem-{(n + j) % 40}", f"src-{(n + j) % 12}", 0, 30_000, -14.0 - j) for j in range(3)]


def pipeline(events: list[Event]) -> dict:
    hm = build_heatmap(events)
    signals = interpret(events).signals
    model = replay(events, recipes=recipes, signals=signals)
    at_s = max(e.wall_time for e in events) / 1000
    cands = [StemCandidate(f"stem-{i}", f"src-{i % 12}", 0.3 + (i % 7) / 10) for i in range(40)]
    batch = select_batch(cands, 20, model, at_s, random.Random(5))
    return {
        "heatmap": hm.to_rows(),
        "candidates": [(c.track_id, c.track_version, c.window_index) for c in hm.candidates()],
        "insights": [(i.insight_id, i.start_ms, i.end_ms) for i in insights_from_candidates(hm.candidates())],
        "signals": sorted((s.session_id, s.wall_time, s.kind, s.window_index or -1) for s in signals),
        "fatigue": {k: round(model.fatigue(k, at_s), 12) for k in sorted(model.states)},
        "batch": [c.stem_id for c in batch],
    }


def test_pipeline_is_identical_through_the_event_sink(open_tenant):
    direct = pipeline(SIM.events)
    assert direct["candidates"] and direct["fatigue"] and direct["batch"]
    in_order = pipeline(store(open_tenant("tenant-a"), batch=len(SIM.events), shuffle_seed=None))
    shuffled = pipeline(store(open_tenant("tenant-b"), batch=97, shuffle_seed=1))
    assert in_order == direct
    assert shuffled == direct


def test_blob_keys_depend_only_on_content(open_tenant):
    a, b = open_tenant("tenant-a"), open_tenant("tenant-b")
    assert a.blobs.put(b"same audio", "stems", ".flac") == b.blobs.put(b"same audio", "stems", ".flac")


def test_same_job_sequence_leases_in_the_same_order(open_tenant):
    def run(q):
        for i, p in enumerate([0, 3, 1, 3, 0, 2]):
            q.enqueue("render", f"r{i}", {"i": i}, priority=p)
        return [(j.key, j.payload) for j in q.lease("render", owner="w", n=6)]

    assert run(open_tenant("tenant-a").jobs) == run(open_tenant("tenant-b").jobs)
