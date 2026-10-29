"""Hand-written listening scripts for each interpretation rule."""
from remixer.analytics.events import Event
from remixer.analytics.interpret import (
    InterpretConfig, classify_next, classify_windows, interpret, interpret_session,
)
from remixer.analytics.simulate import Player, TrackSpec

T = TrackSpec("t1", "v1", 120_000)
T2 = TrackSpec("t2", "v1", 200_000)


def one_listen(p: Player, cfg=InterpretConfig()):
    (listen,) = interpret_session(p.events, cfg)
    return listen


def flags(listen, cfg=InterpretConfig()):
    return {f.index: f for f in classify_windows(listen, cfg)}


def windows(listen, attr):
    return sorted(i for i, f in flags(listen).items() if getattr(f, attr))


def test_plain_listen_plays_every_window():
    p = Player("s").load(T).play().listen_to(120_000).end()
    listen = one_listen(p)
    assert listen.end_reason == "track_end"
    assert windows(listen, "played") == list(range(24))
    assert windows(listen, "skipped") == []


def test_burst_is_one_skip_of_n_presses():
    p = Player("s").load(T).play().listen_to(31_000)
    for _ in range(3):
        p.fwd().wait(400)
    p.listen_to(120_000).end()
    listen = one_listen(p)
    assert [(b.n_presses, b.net_presses) for b in listen.bursts] == [(3, 3)]
    assert windows(listen, "skipped") == [6, 7, 8]
    assert 6 not in windows(listen, "played")


def test_final_press_of_a_burst_is_partly_credited():
    # 4 presses from 38 s land at 58 s; the dislike probably ended inside the last jump (53-58 s),
    # so only 53-56.75 s is credited and window 11 (55-60 s) keeps 1.75 s of skip, below half.
    p = Player("s").load(T).play().listen_to(38_000)
    for _ in range(4):
        p.fwd()
    p.listen_to(120_000).end()
    listen = one_listen(p)
    assert windows(listen, "skipped") == [8, 9, 10]
    full = InterpretConfig(last_press_credit=1.0)
    assert sorted(f.index for f in classify_windows(listen, full) if f.skipped) == [8, 9, 10, 11]


def test_presses_further_apart_than_burst_gap_are_separate_skips():
    p = Player("s").load(T).play().listen_to(31_000).fwd().wait(2500).fwd().listen_to(120_000).end()
    assert [b.n_presses for b in one_listen(p).bursts] == [1, 1]


def test_quick_undo_cancels_skip_and_counts_undone():
    # +5 s over 30-35, hear 2 s of what follows, -5 s: "the skipped part led into something good"
    p = Player("s").load(T).play().listen_to(30_500).fwd().wait(2000).back().listen_to(120_000).end()
    listen = one_listen(p)
    assert listen.bursts[0].cancelled
    assert listen.skipped == []
    assert windows(listen, "skipped") == []
    assert windows(listen, "undone") == [6]
    assert windows(listen, "replayed") == []


def test_overshoot_undo_keeps_the_intended_part_of_the_burst():
    p = Player("s").load(T).play().listen_to(30_500)
    for _ in range(3):
        p.fwd().wait(200)
    p.wait(1000).back().listen_to(120_000).end()
    listen = one_listen(p)
    assert (listen.bursts[0].n_presses, listen.bursts[0].net_presses) == (3, 2)
    assert windows(listen, "skipped") == [6, 7]
    assert windows(listen, "undone") == [8]


def test_back_press_after_undo_window_over_heard_audio_is_a_replay():
    # skip 30.5 -> 35.5, hear to 45.5, back to 40.5: replays 40.5-45.5
    p = Player("s").load(T).play().listen_to(30_500).fwd().wait(10_000).back().listen_to(120_000).end()
    listen = one_listen(p)
    assert windows(listen, "skipped") == [6]
    assert windows(listen, "replayed") == [8]
    assert windows(listen, "undone") == []


def test_replay_of_just_heard_region():
    p = Player("s").load(T).play().listen_to(54_000).back().wait(300).back().listen_to(120_000).end()
    listen = one_listen(p)
    assert listen.replays == [(44_300, 54_000)]
    assert windows(listen, "replayed") == [9, 10]
    assert windows(listen, "skipped") == []


def late_return_script():
    # skip 30 -> 35, 35.4 -> 40.4; hear to 46.9 (past the undo window); back to 41.9, then to 37.2
    p = Player("s").load(T).play().listen_to(30_000).fwd().wait(400).fwd()
    return p.wait(6500).back().wait(300).back().listen_to(120_000).end()


def test_late_return_into_skipped_audio_cancels_that_part():
    listen = one_listen(late_return_script())
    assert listen.late_returns == 1
    assert listen.undone == [(37_200, 40_400)]
    assert windows(listen, "skipped") == [6]
    assert windows(listen, "undone") == [7]
    assert windows(listen, "replayed") == [8]


def test_late_return_rule_can_be_disabled():
    cfg = InterpretConfig(late_return_cancels_skip=False)
    p = late_return_script()
    (listen,) = interpret_session(p.events, cfg)
    assert listen.late_returns == 0
    assert sorted(f.index for f in classify_windows(listen, cfg) if f.skipped) == [6, 7]


def test_reached_excludes_windows_after_early_next():
    p = Player("s").load(T).play().listen_to(12_000).next()
    listen = one_listen(p)
    assert sorted(flags(listen)) == [0, 1, 2]
    assert listen.reached_ms == 12_000


def test_skipped_windows_count_as_reached_but_a_graze_does_not():
    # lands at 20.1 s and leaves at once: window 4 was grazed for 100 ms
    p = Player("s").load(T).play().listen_to(10_000).fwd().wait(100).fwd().next()
    listen = one_listen(p)
    assert sorted(flags(listen)) == [0, 1, 2, 3]
    assert windows(listen, "skipped") == [2, 3]
    assert sorted(f.index for f in classify_windows(listen, InterpretConfig(min_reach_ms=0))) == [0, 1, 2, 3, 4]


def test_seek_is_clamped_to_duration():
    p = Player("s").load(T).play().listen_to(117_000).fwd()
    p.end()
    listen = one_listen(p)
    assert listen.bursts[0].presses == [(117_000, 120_000)]


def test_pause_resume_continues_the_same_listen():
    p = Player("s").load(T).play().listen_to(20_000).pause().wait(60_000).play().listen_to(120_000).end()
    listen = one_listen(p)
    assert listen.heard == [(0, 120_000)]


def test_next_classification():
    cfg = InterpretConfig()
    assert classify_next(10_000, 120_000, cfg) == "early"
    assert classify_next(60_000, 120_000, cfg) == "mid"
    assert classify_next(110_000, 120_000, cfg) == "near_end"
    assert classify_next(108_000, 120_000, cfg) == "near_end"
    assert classify_next(20_000, None, cfg) == "early"
    assert classify_next(90_000, None, cfg) == "mid"


def test_track_level_signals():
    p = Player("s", client_info={"shuffle": True})
    p.load(T).play().listen_to(8_000).next()        # early next on t1
    p.load(T2).play().listen_to(195_000).next()     # next near the end: no signal
    p.load(T).play().listen_to(2_000).previous()    # previous at 2 s: positive for t2 (prior track)
    p.load(T2).play().listen_to(60_000).previous()  # previous at 60 s: restart t2
    res = interpret(p.events)
    track = [(s.kind, s.track_id, s.weight) for s in res.signals if s.level == "track"]
    assert track == [("early_next", "t1", -1.0), ("previous", "t2", 1.0), ("restart", "t2", 1.0)]
    assert all(s.shuffle for s in res.signals)


def test_switching_track_closes_listen_and_session_end_abandons():
    p = Player("s").load(T).play().listen_to(20_000)
    p.load(T2).play().listen_to(30_000).pause()
    a, b = interpret_session(p.events)
    assert (a.end_reason, b.end_reason) == ("switch", "abandoned")
    assert b.heard == [(0, 30_000)]


def test_rating_events_do_not_affect_interpretation():
    p = Player("s").load(T).play().listen_to(40_000).next()
    rating = Event("r1", "s", "t1", "v1", "rate_down", 40_000, p.wall, "source", {})
    assert interpret_session(p.events) == interpret_session([*p.events, rating])


def test_window_signals_carry_documented_weights():
    p = Player("s").load(T).play().listen_to(30_500).fwd().listen_to(54_000).back().listen_to(70_000)
    p.fwd().wait(1000).back().listen_to(120_000).end()
    kinds = {(s.kind, s.window_index, s.weight) for s in interpret(p.events).signals}
    assert ("skip", 6, -1.0) in kinds
    assert ("replay", 10, 1.0) in kinds
    assert ("undo", 14, 0.25) in kinds
