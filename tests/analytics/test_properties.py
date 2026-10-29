"""Property tests: invariants on arbitrary input, and recovery of planted skip patterns."""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from remixer.analytics.events import PLAYBACK_EVENT_TYPES, Event
from remixer.analytics.heatmap import DetectorConfig, build_heatmap
from remixer.analytics.interpret import interpret
from remixer.analytics.intervals import merge, subtract
from remixer.analytics.simulate import PERSONAS, Player, TrackSpec, score, simulate

SLOW = settings(max_examples=12, deadline=None,
                suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])


def assert_consistent(events):
    hb = build_heatmap(events)
    for s in hb.stats():
        assert 0 <= s.reached <= s.track_listens
        for n in (s.played, s.skipped, s.replayed, s.undone):
            assert 0 <= n <= s.reached
    for listen in interpret(events).listens:
        presses = merge(p for b in listen.bursts for p in b.presses)
        assert subtract(listen.skipped, presses) == []
        assert subtract(listen.skipped, subtract(listen.skipped, listen.undone)) == []
        for b in listen.bursts:
            assert 0 <= b.undone <= b.n_presses
    return hb


# These check correctness, including during full-system stress; scale tests own
# performance limits. Scheduling delays must not turn invariants into failures.
@settings(deadline=None)
@given(st.lists(st.tuples(st.sampled_from(PLAYBACK_EVENT_TYPES), st.integers(0, 400_000),
                          st.integers(0, 10_000), st.sampled_from(["a", "b"])), max_size=80))
def test_arbitrary_streams_keep_counts_consistent(steps):
    wall = 1_790_000_000_000
    events = []
    for i, (typ, pos, gap, track) in enumerate(steps):
        wall += gap
        events.append(Event(f"e{i}", "s", track, "v1", typ, pos, wall, "source", {}))
    assert_consistent(events)


action = st.one_of(
    st.tuples(st.just("listen"), st.integers(0, 40_000)),
    st.tuples(st.just("burst"), st.integers(1, 6), st.integers(50, 2500)),
    st.tuples(st.just("back"), st.integers(1, 3), st.integers(50, 8000)),
    st.tuples(st.just("pause"), st.integers(0, 60_000)),
)


@settings(deadline=None)
@given(st.integers(20_000, 400_000), st.lists(action, max_size=25),
       st.sampled_from(["end", "next", "previous", "abandon"]))
def test_player_scripts_keep_counts_consistent(duration, actions, ending):
    t = TrackSpec("t", "v1", duration)
    p = Player("s").load(t).play()
    for a in actions:
        if p.at_end:
            break
        if a[0] == "listen":
            p.wait(a[1])
        elif a[0] == "burst":
            for i in range(a[1]):
                p.wait(a[2] if i else 0).fwd()
        elif a[0] == "back":
            for _ in range(a[1]):
                p.wait(a[2]).back()
        else:
            p.pause().wait(a[1]).play()
    {"end": p.end, "next": p.next, "previous": p.previous, "abandon": lambda: p}[ending]()
    hb = assert_consistent(p.events)
    for listen in interpret(p.events).listens:
        assert all(0 <= s < e <= duration for s, e in listen.heard)


@settings(deadline=None)
@given(duration=st.integers(60_000, 400_000), at_frac=st.floats(0.0, 0.8), presses=st.integers(1, 6),
       gap=st.integers(50, 2000), full_listens=st.integers(0, 12), min_listens=st.integers(1, 3))
def test_window_skipped_once_is_never_flagged(duration, at_frac, presses, gap, full_listens, min_listens):
    t = TrackSpec("t", "v1", duration)
    p = Player("s").load(t).play().listen_to(int(at_frac * duration))
    for i in range(presses):
        p.wait(gap if i else 0).fwd()
    p.listen_to(duration)
    p.end()
    for _ in range(full_listens):
        p.wait(1000).load(t).play().listen_to(duration)
        p.end()
    hb = build_heatmap(p.events)
    assert hb.candidates(DetectorConfig(min_track_listens=min_listens)) == []


@settings(deadline=None)
@given(duration=st.integers(60_000, 400_000), listens=st.lists(
    st.tuples(st.floats(0.0, 0.7), st.integers(1, 5), st.integers(50, 2000), st.integers(0, 5900),
              st.integers(50, 5900)), min_size=1, max_size=10))
def test_skipped_then_undone_is_never_counted_or_flagged(duration, listens):
    t = TrackSpec("t", "v1", duration)
    p = Player("s")
    for at_frac, presses, gap, listen_after, back_gap in listens:
        p.load(t).play().listen_to(int(at_frac * duration))
        for i in range(presses):
            p.wait(gap if i else 0).fwd()
        p.wait(listen_after)
        for i in range(presses):
            p.wait(back_gap if i else 0).back()
        p.listen_to(duration)
        p.end()
        p.wait(1000)
    hb = build_heatmap(p.events)
    assert all(s.skipped == 0 for s in hb.stats())
    assert hb.candidates(DetectorConfig(min_track_listens=1, min_skips=1)) == []


def expected_skip_prob(mix):
    return sum(w * PERSONAS[n].skip_prob for n, w in mix.items()) / sum(mix.values())


# Recovery is promised when the owner skips the part in a clear majority of listens.
mixes = st.dictionaries(st.sampled_from(sorted(PERSONAS)), st.floats(0.05, 1.0), min_size=1).filter(
    lambda m: expected_skip_prob(m) >= 0.75)


@settings(SLOW, derandomize=True)
@given(seed=st.integers(0, 100_000), mix=mixes)
def test_detector_recovers_planted_windows(seed, mix, report):
    sim = simulate(n_tracks=30, n_sessions=400, seed=seed, mix=mix)
    r = score(build_heatmap(sim.events).candidates(), sim)
    report(f"property seed={seed:6d} p(skip)={expected_skip_prob(mix):.2f} mix={','.join(sorted(mix))}: "
           f"precision={r['precision']:.3f} "
           f"recall={r['recall']:.3f} tp={r['tp']} fp={r['fp']} fn={r['fn']}")
    assert r["recall"] >= 0.9
    assert r["precision"] >= 0.9
    assert r["flagged_teases"] == 0
    assert r["flagged_loved"] == 0


def test_detector_precision_recall_over_fixed_seeds(report):
    tp = fp = fn = 0
    for seed in range(20):
        sim = simulate(seed=seed)
        r = score(build_heatmap(sim.events).candidates(), sim)
        assert r["flagged_teases"] == r["flagged_loved"] == 0
        tp, fp, fn = tp + r["tp"], fp + r["fp"], fn + r["fn"]
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    report(f"20 fixed seeds, default persona mix, 40 tracks x 400 sessions each: "
           f"precision={precision:.4f} recall={recall:.4f} (tp={tp} fp={fp} fn={fn})")
    assert precision >= 0.95
    assert recall >= 0.97


def test_per_persona_report(report):
    for name in sorted(PERSONAS):
        sim = simulate(seed=11, mix={name: 1.0})
        r = score(build_heatmap(sim.events).candidates(), sim)
        report(f"persona {name:15s} alone: precision={r['precision']:.3f} recall={r['recall']:.3f}")
        assert r["precision"] >= 0.9
        assert r["flagged_teases"] == 0
        if name != "lean_back":  # skips only half the time: not a clear majority by design
            assert r["recall"] >= 0.9


def test_sparse_listening_only_flags_tracks_with_three_listens(report):
    sim = simulate(n_tracks=200, n_sessions=60, seed=5, mix={"attentive": 1.0}, planted_fraction=1.0)
    hb = build_heatmap(sim.events)
    cands = hb.candidates()
    assert any(n < 3 for n in hb.listens.values())
    assert all(hb.listens[(c.track_id, c.track_version)] >= 3 for c in cands)
    r = score(cands, sim)
    report(f"sparse (200 tracks, 60 sessions): precision={r['precision']:.3f} recall={r['recall']:.3f}")
    assert r["precision"] >= 0.9


def test_simulation_is_deterministic_and_synthetic():
    a, b = simulate(seed=3, n_sessions=50), simulate(seed=3, n_sessions=50)
    assert a.events == b.events
    assert all(e.client_info["synthetic"] for e in a.events)
