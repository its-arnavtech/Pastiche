"""Tests for scripts/agentctl.py. Each test runs against a throwaway git repo."""
from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "agentctl", Path(__file__).resolve().parent.parent / "scripts" / "agentctl.py")
agentctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agentctl)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTL_ROOT", str(tmp_path))
    for args in (["init", "-q", "-b", "dev"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


def run(*argv):
    agentctl.main(list(argv))


def task_meta(repo, tid):
    return agentctl.read_doc(agentctl.find_task(tid))[0]


def test_frontmatter_roundtrip(tmp_path):
    p = tmp_path / "x.md"
    agentctl.write_doc(p, {"id": "T-001", "depends_on": ["T-002", "T-003"], "owner": ""}, "body", agentctl.TASK_KEYS)
    meta, body = agentctl.read_doc(p)
    assert meta == {"id": "T-001", "depends_on": ["T-002", "T-003"], "owner": ""}
    assert body.strip() == "body"


def test_task_new_ids_increment(repo):
    run("task", "new", "--title", "First thing", "--lane", "gpu")
    run("task", "new", "--title", "Second: thing", "--depends-on", "T-001")
    names = sorted(p.name for p in (repo / "tasks").iterdir())
    assert names == ["T-001_first-thing.md", "T-002_second-thing.md"]
    m = task_meta(repo, "T-002")
    assert m["status"] == "todo" and m["depends_on"] == ["T-001"] and m["title"] == "Second: thing"


def test_claim_commits_only_task_file(repo):
    run("task", "new", "--title", "Claim me")
    (repo / "other.txt").write_text("someone else's work\n")
    subprocess.run(["git", "add", "other.txt"], cwd=repo, check=True)
    run("task", "claim", "T-001", "--agent", "opus-cc")
    m = task_meta(repo, "T-001")
    assert m["status"] == "in_progress" and m["owner"] == "opus-cc" and m["branch"] == "dev"
    committed = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo,
                               capture_output=True, text=True).stdout.split()
    assert committed == ["tasks/T-001_claim-me.md"]
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo,
                            capture_output=True, text=True).stdout.split()
    assert staged == ["other.txt"]  # other agent's staged work untouched


def test_claim_rejects_non_todo(repo):
    run("task", "new", "--title", "x")
    run("task", "claim", "T-001", "--agent", "a", "--no-commit")
    with pytest.raises(SystemExit):
        run("task", "claim", "T-001", "--agent", "b", "--no-commit")


def test_heartbeat_handoff_done(repo):
    run("task", "new", "--title", "x")
    run("task", "claim", "T-001", "--agent", "a", "--no-commit")
    with pytest.raises(SystemExit):
        run("task", "heartbeat", "T-001", "--agent", "b")
    run("task", "heartbeat", "T-001", "--agent", "a", "--note", "halfway")
    run("task", "handoff", "T-001", "--agent", "a", "--note", "ready", "--status", "review", "--no-commit")
    assert task_meta(repo, "T-001")["status"] == "review"
    run("task", "done", "T-001", "--agent", "a", "--no-commit")
    _, body = agentctl.read_doc(agentctl.find_task("T-001"))
    assert task_meta(repo, "T-001")["status"] == "done"
    assert "halfway" in body and "handoff: ready" in body and body.rstrip().endswith("a: done")


def _age_claim(tid, hours):
    path = agentctl.find_task(tid)
    meta, body = agentctl.read_doc(path)
    old = agentctl.iso(agentctl.now() - dt.timedelta(hours=hours))
    meta["claimed_at"] = meta["heartbeat_at"] = old
    agentctl.write_doc(path, meta, body, agentctl.TASK_KEYS)


def test_takeover_only_when_stale(repo):
    run("task", "new", "--title", "x")
    run("task", "claim", "T-001", "--agent", "a", "--no-commit")
    with pytest.raises(SystemExit):
        run("task", "takeover", "T-001", "--agent", "b", "--reason", "idle", "--no-commit")
    _age_claim("T-001", 3)
    run("task", "takeover", "T-001", "--agent", "b", "--reason", "idle", "--no-commit")
    assert task_meta(repo, "T-001")["owner"] == "b"
    entries = list((repo / "changelog").glob("*_b_takeover-t-001.md"))
    assert len(entries) == 1


def test_recent_changelog_keeps_claim_fresh(repo):
    run("task", "new", "--title", "x")
    run("task", "claim", "T-001", "--agent", "a", "--no-commit")
    _age_claim("T-001", 3)
    run("log", "--agent", "a", "--type", "feat", "--slug", "progress", "--what", "stuff")
    assert not agentctl.is_stale(task_meta(repo, "T-001"))


def test_changelog_regenerates_newest_first(repo):
    a = agentctl.write_changelog("a", "feat", "one", ["T-001"], ["x.py"], "first", "w", "v", "n")
    b = agentctl.write_changelog("b", "fix", "two", [], [], "second", "w", "v", "n")
    for p, ts in ((a, "2026-01-01T00:00:00Z"), (b, "2026-01-02T00:00:00Z")):
        meta, body = agentctl.read_doc(p)
        meta["ts"] = ts
        agentctl.write_doc(p, meta, body, agentctl.CHANGE_KEYS)
    run("changelog")
    text = (repo / "CHANGELOG.md").read_text()
    assert text.index("second") < text.index("first")
    assert "### What changed" in text


def test_changelog_rejects_bad_type(repo):
    with pytest.raises(SystemExit):
        agentctl.write_changelog("a", "nope", "s", [], [], "w", "w", "v", "n")


def test_locks(repo, capsys):
    run("lock", "acquire", "gpu", "--owner", "a", "--ttl", "5", "--note", "demucs")
    with pytest.raises(SystemExit):
        run("lock", "acquire", "gpu", "--owner", "b")
    run("lock", "acquire", "gpu", "--owner", "a", "--ttl", "10")  # refresh by owner
    run("lock", "acquire", "cpu", "--owner", "b")  # lanes are independent
    with pytest.raises(SystemExit):
        run("lock", "release", "gpu", "--owner", "b")
    run("lock", "release", "gpu", "--owner", "a")
    run("lock", "acquire", "gpu", "--owner", "b")
    capsys.readouterr()
    run("lock", "status")
    out = capsys.readouterr().out
    assert "gpu  held by b" in out and "npu  free" in out


def test_expired_lock_is_free(repo):
    run("lock", "acquire", "npu", "--owner", "a", "--ttl", "1")
    p = repo / ".locks" / "npu.json"
    data = agentctl.json.loads(p.read_text())
    data["expires_at"] = agentctl.iso(agentctl.now() - dt.timedelta(minutes=1))
    p.write_text(agentctl.json.dumps(data))
    run("lock", "acquire", "npu", "--owner", "b")
    assert agentctl.read_lock("npu")["owner"] == "b"


def test_status_runs(repo, capsys):
    run("task", "new", "--title", "x")
    run("task", "claim", "T-001", "--agent", "a", "--no-commit")
    run("status")
    out = capsys.readouterr().out
    assert "branch: dev" in out and "T-001" in out and "locks:" in out
