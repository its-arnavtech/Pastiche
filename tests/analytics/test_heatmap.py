from remixer.analytics.heatmap import DetectorConfig, HeatmapBuilder, build_heatmap
from remixer.analytics.simulate import Player, TrackSpec

T = TrackSpec("t1", "v1", 120_000)


def skip_listen(p: Player, at=30_500, presses=1, undo=False, track=T):
    p.load(track).play().listen_to(at)
    for i in range(presses):
        if i:
            p.wait(300)
        p.fwd()
    if undo:
        p.wait(1500).back()
    p.listen_to(track.duration_ms).end()
    p.wait(1000)


def full_listen(p: Player, track=T):
    p.load(track).play().listen_to(track.duration_ms).end()
    p.wait(1000)


def stats_for(hb, w, version="v1"):
    return next(s for s in hb.stats() if s.window_index == w and s.track_version == version)


def test_majority_skip_with_three_listens_is_candidate():
    p = Player("s")
    skip_listen(p)
    skip_listen(p)
    full_listen(p)
    hb = build_heatmap(p.events)
    s = stats_for(hb, 6)
    assert (s.track_listens, s.reached, s.skipped, s.played) == (3, 3, 2, 1)
    assert [c.window_index for c in hb.candidates()] == [6]


def test_needs_three_listens_of_the_track():
    p = Player("s")
    skip_listen(p)
    skip_listen(p)
    assert build_heatmap(p.events).candidates() == []


def test_single_skip_is_never_a_candidate():
    p = Player("s")
    skip_listen(p)
    hb = build_heatmap(p.events)
    assert hb.candidates(DetectorConfig(min_track_listens=1)) == []


def test_skipped_then_undone_is_not_a_candidate():
    p = Player("s")
    for _ in range(5):
        skip_listen(p, undo=True)
    hb = build_heatmap(p.events)
    s = stats_for(hb, 6)
    assert (s.skipped, s.undone) == (0, 5)
    assert hb.candidates() == []


def test_frequent_undos_block_candidate_even_with_majority_skips():
    p = Player("s")
    for _ in range(3):
        skip_listen(p)
    skip_listen(p, undo=True)
    hb = build_heatmap(p.events)
    s = stats_for(hb, 6)
    assert (s.reached, s.skipped, s.undone) == (4, 3, 1)
    assert hb.candidates() == []
    assert [c.window_index for c in hb.candidates(DetectorConfig(max_undo_rate=0.25))] == [6]


def test_denominator_is_listens_that_reached_the_window():
    # 10 listens, 7 leave at 20 s; the 3 that reach 100 s all skip it.
    p = Player("s")
    for _ in range(7):
        p.load(T).play().listen_to(20_000).next()
    for _ in range(3):
        skip_listen(p, at=100_500)
    hb = build_heatmap(p.events)
    s = stats_for(hb, 20)
    assert (s.track_listens, s.reached, s.skipped) == (10, 3, 3)
    assert s.skip_rate == 1.0
    assert [c.window_index for c in hb.candidates()] == [20]


def test_minority_skip_is_not_a_candidate():
    p = Player("s")
    skip_listen(p)
    skip_listen(p)
    full_listen(p)
    full_listen(p)
    assert build_heatmap(p.events).candidates() == []


def test_threshold_is_configurable():
    p = Player("s")
    skip_listen(p)
    skip_listen(p)
    full_listen(p)
    full_listen(p)
    hb = build_heatmap(p.events)
    assert [c.window_index for c in hb.candidates(DetectorConfig(min_skip_rate=0.5))] == [6]


def test_burst_counts_each_covered_window_once_per_listen():
    p = Player("s")
    for _ in range(3):
        skip_listen(p, presses=3)
    hb = build_heatmap(p.events)
    assert [c.window_index for c in hb.candidates()] == [6, 7, 8]
    assert all(stats_for(hb, w).skipped == 3 for w in (6, 7, 8))


def test_rerendered_version_does_not_inherit_events():
    v2 = TrackSpec("t1", "v2", 120_000)
    p = Player("s")
    for _ in range(3):
        skip_listen(p)
    full_listen(p, v2)
    hb = build_heatmap(p.events)
    assert {(c.track_version, c.window_index) for c in hb.candidates()} == {("v1", 6)}
    assert stats_for(hb, 6, "v2").skipped == 0
    assert hb.listens == {("t1", "v1"): 3, ("t1", "v2"): 1}


def test_merge_equals_single_pass():
    a, b = Player("a"), Player("b")
    for _ in range(2):
        skip_listen(a)
    skip_listen(b, presses=2)
    full_listen(b)
    whole = build_heatmap([*a.events, *b.events])
    merged = HeatmapBuilder().merge(build_heatmap(a.events)).merge(build_heatmap(b.events))
    assert merged.to_rows() == whole.to_rows()


def test_last_window_is_partial():
    t = TrackSpec("t9", "v1", 12_000)
    p = Player("s")
    full_listen(p, t)
    rows = list(build_heatmap(p.events).stats())
    assert [(s.start_ms, s.end_ms) for s in rows] == [(0, 5000), (5000, 10_000), (10_000, 12_000)]
    assert all(s.played == 1 for s in rows)
