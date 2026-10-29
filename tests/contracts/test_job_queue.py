import time


def test_enqueue_is_idempotent_on_kind_and_key(adapters):
    q = adapters.jobs
    assert q.enqueue("separate", "track-1", {"model": "htdemucs"}) is True
    assert q.enqueue("separate", "track-1", {"model": "other"}) is False
    assert q.enqueue("embed", "track-1") is True
    assert q.counts("separate") == {"queued": 1}
    assert sum(q.counts().values()) == 2


def test_lease_is_exclusive_and_ack_completes(adapters):
    q = adapters.jobs
    q.enqueue("separate", "track-1", {"model": "htdemucs"})
    [job] = q.lease("separate", owner="w1")
    assert (job.kind, job.key, job.payload, job.attempts) == ("separate", "track-1", {"model": "htdemucs"}, 1)
    assert q.lease("separate", owner="w2") == []
    q.ack(job.id, {"stems": 4})
    assert q.counts("separate") == {"done": 1}
    assert q.lease("separate", owner="w2") == []


def test_priority_then_fifo(adapters):
    q = adapters.jobs
    for k in ("a", "b", "c"):
        q.enqueue("render", k)
    q.enqueue("render", "urgent", priority=5)
    assert [j.key for j in q.lease("render", owner="w", n=4)] == ["urgent", "a", "b", "c"]


def test_fail_retries_then_gives_up(adapters):
    q = adapters.jobs
    q.enqueue("separate", "flaky")
    attempts = 0
    while job := q.lease("separate", owner="w"):
        attempts += 1
        q.fail(job[0].id, "CUDA OOM", retry=True)
        assert attempts < 20, "retries must be bounded"
    assert attempts >= 2
    assert q.counts("separate") == {"failed": 1}


def test_fail_without_retry_is_final(adapters):
    q = adapters.jobs
    q.enqueue("separate", "corrupt")
    [job] = q.lease("separate", owner="w")
    q.fail(job.id, "not audio", retry=False)
    assert q.lease("separate", owner="w") == []
    assert q.counts("separate") == {"failed": 1}


def test_release_does_not_count_an_attempt(adapters):
    q = adapters.jobs
    q.enqueue("separate", "t")
    for _ in range(10):
        [job] = q.lease("separate", owner="w")
        q.release(job.id)
    [job] = q.lease("separate", owner="w")
    assert job.attempts == 1


def test_expired_lease_is_taken_over_and_extend_prevents_it(adapters):
    q = adapters.jobs
    q.enqueue("separate", "crashed")
    q.enqueue("separate", "slow")
    crashed, slow = q.lease("separate", owner="w1", n=2, lease_s=0.2)
    q.extend(slow.id, lease_s=60)
    time.sleep(0.3)
    taken = q.lease("separate", owner="w2", n=2)
    assert [j.key for j in taken] == ["crashed"]
    assert taken[0].attempts == 2


def test_durable_across_reopen(open_tenant):
    open_tenant("tenant-a").jobs.enqueue("separate", "survives")
    [job] = open_tenant("tenant-a").jobs.lease("separate", owner="w")
    assert job.key == "survives"
