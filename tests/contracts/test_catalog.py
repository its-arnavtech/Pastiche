TRACK = {"track_id": "t-1", "title": "First", "artist": "A", "duration_s": 61.5, "synthetic": 1}


def test_upsert_inserts_then_updates(adapters):
    c = adapters.catalog
    c.upsert("tracks", TRACK, key=["track_id"])
    c.upsert("tracks", TRACK | {"title": "Renamed"}, key=["track_id"])
    rows = c.query("SELECT track_id, title, synthetic FROM tracks")
    assert rows == [{"track_id": "t-1", "title": "Renamed", "synthetic": 1}]


def test_upsert_with_key_only_row_is_a_noop_on_conflict(adapters):
    c = adapters.catalog
    c.upsert("tracks", TRACK, key=["track_id"])
    c.upsert("tracks", {"track_id": "t-1"}, key=["track_id"])
    assert c.get("tracks", track_id="t-1")["title"] == "First"


def test_insert_returns_integer_id(adapters):
    rid = adapters.catalog.insert("embeddings", {"owner_id": "s-1", "owner_kind": "stem", "model": "clap",
                                                 "model_version": "1"})
    assert isinstance(rid, int)
    assert adapters.catalog.get("embeddings", row_id=rid)["owner_id"] == "s-1"


def test_get_missing_is_none_and_query_binds_params(adapters):
    c = adapters.catalog
    assert c.get("tracks", track_id="nope") is None
    c.upsert("tracks", TRACK, key=["track_id"])
    c.upsert("tracks", TRACK | {"track_id": "t-2", "title": "Second"}, key=["track_id"])
    assert c.query("SELECT title FROM tracks WHERE track_id = ?", ["t-2"]) == [{"title": "Second"}]
    assert c.query("SELECT title FROM tracks WHERE title = ?", ["x' OR '1'='1"]) == []


def test_synthetic_flag_round_trips(adapters):
    c = adapters.catalog
    c.upsert("tracks", TRACK, key=["track_id"])
    c.upsert("tracks", TRACK | {"track_id": "real", "synthetic": 0}, key=["track_id"])
    assert [r["track_id"] for r in c.query("SELECT track_id FROM tracks WHERE synthetic = 0")] == ["real"]


def test_durable_across_reopen(open_tenant):
    open_tenant("tenant-a").catalog.upsert("tracks", TRACK, key=["track_id"])
    assert open_tenant("tenant-a").catalog.get("tracks", track_id="t-1")["title"] == "First"
