#!/usr/bin/env python3
"""agentctl: coordination CLI for the agents working on this repo.

Standard library only. Subcommands:

    status
    log --agent ID --type TYPE --slug SLUG [--tasks ..] [--files ..] --what .. --why .. --verify .. --next ..
    changelog
    task new|claim|heartbeat|handoff|done|takeover|list
    lock acquire|release|status

Tasks live in tasks/T-###_slug.md, changelog entries in changelog/*.md,
locks in .locks/<lane>.json (gitignored). Set AGENTCTL_ROOT to point at a
different repo root (used by the tests).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TASK_STATUSES = ("todo", "in_progress", "blocked", "review", "done")
LANES = ("gpu", "cpu", "npu", "none")
LOCK_LANES = ("gpu", "cpu", "npu")
CHANGE_TYPES = ("feat", "fix", "perf", "docs", "decision", "handoff", "blocker", "bench", "merge")
STALE_AFTER = dt.timedelta(hours=2)
TASK_KEYS = (
    "id", "title", "status", "owner", "branch", "lane", "depends_on",
    "owns_paths", "claimed_at", "heartbeat_at", "priority",
)
CHANGE_KEYS = ("ts", "agent", "branch", "type", "tasks", "files")


# ---------------------------------------------------------------- helpers

def root() -> Path:
    env = os.environ.get("AGENTCTL_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def age(s: str) -> str:
    t = parse_iso(s)
    if t is None:
        return "-"
    mins = int((now() - t).total_seconds() // 60)
    return f"{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"{mins}m"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "entry"


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=root(), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def current_branch() -> str:
    try:
        return git("rev-parse", "--abbrev-ref", "HEAD", check=False) or "?"
    except FileNotFoundError:
        return "?"


def commit_paths(paths: list[Path], message: str) -> None:
    """Commit exactly these paths (never anything else in the index)."""
    rel = [str(p.relative_to(root())).replace("\\", "/") for p in paths]
    git("add", "--", *rel)
    git("commit", "-m", message, "--only", "--", *rel)


# ------------------------------------------------------------ frontmatter

def _fmt_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return "" if v is None else str(v)


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [x.strip() for x in inner.split(",") if x.strip()] if inner else []
    return raw


def read_doc(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = _parse_value(v)
    return meta, body.lstrip("\n")


def write_doc(path: Path, meta: dict, body: str, keys: tuple[str, ...]) -> None:
    ordered = [k for k in keys if k in meta] + [k for k in meta if k not in keys]
    fm = "\n".join(f"{k}: {_fmt_value(meta[k])}".rstrip() for k in ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}\n---\n\n{body.rstrip()}\n", encoding="utf-8", newline="\n")


# ------------------------------------------------------------------ tasks

def tasks_dir() -> Path:
    return root() / "tasks"


def task_files() -> list[Path]:
    d = tasks_dir()
    return sorted(d.glob("T-*.md")) if d.exists() else []


def find_task(task_id: str) -> Path:
    task_id = task_id.upper()
    for p in task_files():
        if p.name.startswith(task_id + "_") or p.stem == task_id:
            return p
    raise SystemExit(f"no task {task_id}")


def next_task_id() -> str:
    nums = [int(m.group(1)) for p in task_files() if (m := re.match(r"T-(\d+)", p.name))]
    return f"T-{(max(nums) + 1 if nums else 1):03d}"


def append_log(body: str, agent: str, note: str) -> str:
    line = f"- {iso(now())} {agent}: {note}"
    marker = "## Progress and handoff log"
    if marker not in body:
        body = body.rstrip() + f"\n\n{marker}\n"
    return body.rstrip() + "\n" + line + "\n"


def last_changelog_by(agent: str) -> dt.datetime | None:
    latest = None
    for p in changelog_files():
        meta, _ = read_doc(p)
        if meta.get("agent") == agent and (t := parse_iso(meta.get("ts", ""))):
            latest = t if latest is None or t > latest else latest
    return latest


def is_stale(meta: dict) -> bool:
    if meta.get("status") != "in_progress":
        return False
    hb = parse_iso(meta.get("heartbeat_at", "")) or parse_iso(meta.get("claimed_at", ""))
    if hb and now() - hb <= STALE_AFTER:
        return False
    owner = meta.get("owner", "")
    last = last_changelog_by(owner) if owner else None
    return not (last and now() - last <= STALE_AFTER)


def cmd_task_new(a) -> None:
    tid = a.id or next_task_id()
    path = tasks_dir() / f"{tid}_{slugify(a.title)}.md"
    meta = {
        "id": tid, "title": a.title, "status": "todo", "owner": a.owner or "",
        "branch": a.branch or "", "lane": a.lane, "depends_on": a.depends_on or [],
        "owns_paths": a.owns_paths or [], "claimed_at": "", "heartbeat_at": "",
        "priority": a.priority,
    }
    body = (
        f"## Goal\n\n{a.goal or 'TBD'}\n\n"
        f"## Definition of done\n\n{a.dod or 'TBD'}\n\n"
        "## Progress and handoff log\n\n"
        f"- {iso(now())} {a.agent}: created\n"
    )
    write_doc(path, meta, body, TASK_KEYS)
    if a.commit:
        commit_paths([path], f"task: create {tid} {a.title}")
    print(path.relative_to(root()))


def _update_task(task_id: str, agent: str, note: str, commit: bool, msg: str, **changes) -> Path:
    path = find_task(task_id)
    meta, body = read_doc(path)
    meta.update(changes)
    body = append_log(body, agent, note)
    write_doc(path, meta, body, TASK_KEYS)
    if commit:
        commit_paths([path], msg)
    return path


def cmd_task_claim(a) -> None:
    meta, _ = read_doc(find_task(a.task))
    if meta.get("status") != "todo":
        raise SystemExit(f"{a.task} is {meta.get('status')}, only todo tasks can be claimed")
    t = iso(now())
    _update_task(a.task, a.agent, "claimed", a.commit, f"task: {a.agent} claims {a.task}",
                 status="in_progress", owner=a.agent, branch=a.branch or current_branch(),
                 claimed_at=t, heartbeat_at=t)
    print(f"{a.task} claimed by {a.agent}")


def cmd_task_heartbeat(a) -> None:
    meta, _ = read_doc(find_task(a.task))
    if meta.get("owner") != a.agent:
        raise SystemExit(f"{a.task} is owned by {meta.get('owner')!r}, not {a.agent}")
    path = find_task(a.task)
    meta, body = read_doc(path)
    meta["heartbeat_at"] = iso(now())
    if a.note:
        body = append_log(body, a.agent, a.note)
    write_doc(path, meta, body, TASK_KEYS)
    if a.commit:
        commit_paths([path], f"task: {a.agent} heartbeat {a.task}")
    print(f"{a.task} heartbeat")


def cmd_task_handoff(a) -> None:
    changes = {"heartbeat_at": iso(now())}
    if a.status:
        changes["status"] = a.status
    _update_task(a.task, a.agent, f"handoff: {a.note}", a.commit,
                 f"task: {a.agent} handoff {a.task}", **changes)
    print(f"{a.task} handoff recorded")


def cmd_task_done(a) -> None:
    _update_task(a.task, a.agent, f"done: {a.note}" if a.note else "done", a.commit,
                 f"task: {a.agent} done {a.task}", status="done", heartbeat_at=iso(now()))
    print(f"{a.task} done")


def cmd_task_takeover(a) -> None:
    meta, _ = read_doc(find_task(a.task))
    if not a.force and not is_stale(meta):
        raise SystemExit(f"{a.task} is not stale (owner {meta.get('owner')}, heartbeat {age(meta.get('heartbeat_at', ''))} ago)")
    old = meta.get("owner", "")
    t = iso(now())
    path = _update_task(a.task, a.agent, f"takeover from {old}: {a.reason}", False, "",
                        owner=a.agent, status="in_progress", claimed_at=t, heartbeat_at=t,
                        branch=current_branch())
    entry = write_changelog(a.agent, "handoff", f"takeover-{a.task.lower()}", [a.task.upper()],
                            [str(path.relative_to(root())).replace("\\", "/")],
                            what=f"{a.agent} took over {a.task} from {old}.",
                            why=a.reason, verify=f"python scripts/agentctl.py task list",
                            nxt=f"{old}: check the task log before resuming anything on {a.task}.")
    if a.commit:
        commit_paths([path, entry], f"task: {a.agent} takes over {a.task} from {old}")
    print(f"{a.task} taken over by {a.agent}")


def cmd_task_list(a) -> None:
    for p in task_files():
        meta, _ = read_doc(p)
        if a.status and meta.get("status") != a.status:
            continue
        if a.owner and meta.get("owner") != a.owner:
            continue
        print(f"{meta.get('id', p.stem):7} {meta.get('status', '?'):12} {meta.get('lane', ''):5} "
              f"{meta.get('owner', '') or '-':12} {meta.get('title', '')}")


# -------------------------------------------------------------- changelog

def changelog_dir() -> Path:
    return root() / "changelog"


def changelog_files() -> list[Path]:
    d = changelog_dir()
    return sorted(d.glob("*.md")) if d.exists() else []


def write_changelog(agent, typ, slug, tasks, files, what, why, verify, nxt) -> Path:
    if typ not in CHANGE_TYPES:
        raise SystemExit(f"type must be one of {CHANGE_TYPES}")
    t = now()
    base = f"{t.strftime('%Y%m%d-%H%M%S')}_{agent}_{slugify(slug)}"
    path = changelog_dir() / f"{base}.md"
    n = 1
    while path.exists():
        n += 1
        path = changelog_dir() / f"{base}-{n}.md"
    meta = {"ts": iso(t), "agent": agent, "branch": current_branch(), "type": typ,
            "tasks": tasks or [], "files": files or []}
    body = (f"## What changed\n\n{what}\n\n## Why\n\n{why}\n\n"
            f"## How to verify\n\n{verify}\n\n## Next / handoff\n\n{nxt}\n")
    write_doc(path, meta, body, CHANGE_KEYS)
    return path


def cmd_log(a) -> None:
    path = write_changelog(a.agent, a.type, a.slug, a.tasks, a.files, a.what, a.why, a.verify, a.next)
    print(path.relative_to(root()))


def cmd_changelog(a) -> None:
    entries = []
    for p in changelog_files():
        meta, body = read_doc(p)
        entries.append((meta.get("ts", ""), p.name, meta, body))
    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
    out = ["# Changelog", "", "Generated by `python scripts/agentctl.py changelog` from `changelog/`. Do not edit by hand.", ""]
    for ts, name, meta, body in entries:
        tasks = ", ".join(meta.get("tasks") or []) or "-"
        out.append(f"## {ts} {meta.get('agent', '?')} [{meta.get('type', '?')}] {name[:-3]}")
        out.append("")
        out.append(f"Branch: `{meta.get('branch', '?')}`. Tasks: {tasks}.")
        out.append("")
        out.append(re.sub(r"^## ", "### ", body.strip(), flags=re.M))
        out.append("")
    (root() / "CHANGELOG.md").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"CHANGELOG.md: {len(entries)} entries")


# ------------------------------------------------------------------ locks

def locks_dir() -> Path:
    d = root() / ".locks"
    d.mkdir(exist_ok=True)
    return d


def read_lock(lane: str) -> dict | None:
    p = locks_dir() / f"{lane}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    exp = parse_iso(data.get("expires_at", ""))
    if exp is None or exp <= now():
        return None
    return data


def cmd_lock_acquire(a) -> None:
    p = locks_dir() / f"{a.lane}.json"
    held = read_lock(a.lane)
    if held and held.get("owner") != a.owner:
        raise SystemExit(f"{a.lane} lock held by {held['owner']} until {held['expires_at']} ({held.get('note', '')})")
    t = now()
    data = {"lane": a.lane, "owner": a.owner, "note": a.note or "", "acquired_at": iso(t),
            "expires_at": iso(t + dt.timedelta(minutes=a.ttl)), "pid": os.getpid()}
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if held is None and not p.exists():
        try:
            os.link(tmp, p)  # atomic create-if-absent
            tmp.unlink()
        except FileExistsError:
            tmp.unlink()
            return cmd_lock_acquire(a)
    else:
        os.replace(tmp, p)
    print(f"{a.lane} lock acquired by {a.owner} until {data['expires_at']}")


def cmd_lock_release(a) -> None:
    p = locks_dir() / f"{a.lane}.json"
    held = read_lock(a.lane)
    if held and held.get("owner") != a.owner and not a.force:
        raise SystemExit(f"{a.lane} lock is held by {held['owner']}, not {a.owner}")
    p.unlink(missing_ok=True)
    print(f"{a.lane} lock released")


def cmd_lock_status(a) -> None:
    for lane in LOCK_LANES:
        held = read_lock(lane)
        if held:
            print(f"{lane:4} held by {held['owner']} until {held['expires_at']}  {held.get('note', '')}")
        else:
            print(f"{lane:4} free")


# ----------------------------------------------------------------- status

def cmd_status(a) -> None:
    print(f"branch: {current_branch()}")
    print("\nopen tasks:")
    for p in task_files():
        meta, _ = read_doc(p)
        st = meta.get("status")
        if st == "done":
            continue
        extra = ""
        if st == "in_progress":
            extra = f"  heartbeat {age(meta.get('heartbeat_at', ''))} ago" + ("  STALE" if is_stale(meta) else "")
        print(f"  {meta.get('id'):7} {st:12} {meta.get('owner') or '-':12} {meta.get('title')}{extra}")
    print("\nlocks:")
    for lane in LOCK_LANES:
        held = read_lock(lane)
        print(f"  {lane:4} " + (f"held by {held['owner']} until {held['expires_at']}  {held.get('note', '')}" if held else "free"))
    print("\nlast 15 changelog entries:")
    entries = []
    for p in changelog_files():
        meta, _ = read_doc(p)
        entries.append((meta.get("ts", ""), p.name, meta))
    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
    for ts, name, meta in entries[:15]:
        print(f"  {ts} {meta.get('agent', '?'):12} {meta.get('type', '?'):8} {name}")


# -------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agentctl", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("changelog").set_defaults(fn=cmd_changelog)

    lg = sub.add_parser("log")
    lg.add_argument("--agent", required=True)
    lg.add_argument("--type", required=True, choices=CHANGE_TYPES)
    lg.add_argument("--slug", required=True)
    lg.add_argument("--tasks", nargs="*", default=[])
    lg.add_argument("--files", nargs="*", default=[])
    lg.add_argument("--what", required=True)
    lg.add_argument("--why", default="-")
    lg.add_argument("--verify", default="-")
    lg.add_argument("--next", default="-")
    lg.set_defaults(fn=cmd_log)

    tk = sub.add_parser("task").add_subparsers(dest="tcmd", required=True)

    def with_commit(p):
        p.add_argument("--no-commit", dest="commit", action="store_false")
        return p

    tn = tk.add_parser("new")
    tn.add_argument("--title", required=True)
    tn.add_argument("--id")
    tn.add_argument("--agent", default="unknown", help="who creates it")
    tn.add_argument("--owner", help="intended owner")
    tn.add_argument("--branch")
    tn.add_argument("--lane", choices=LANES, default="none")
    tn.add_argument("--priority", default="P2")
    tn.add_argument("--depends-on", nargs="*", default=[])
    tn.add_argument("--owns-paths", nargs="*", default=[])
    tn.add_argument("--goal")
    tn.add_argument("--dod")
    tn.add_argument("--commit", action="store_true", help="commit the new task file")
    tn.set_defaults(fn=cmd_task_new)

    tc = with_commit(tk.add_parser("claim"))
    tc.add_argument("task")
    tc.add_argument("--agent", required=True)
    tc.add_argument("--branch")
    tc.set_defaults(fn=cmd_task_claim)

    th = tk.add_parser("heartbeat")
    th.add_argument("task")
    th.add_argument("--agent", required=True)
    th.add_argument("--note")
    th.add_argument("--commit", action="store_true")
    th.set_defaults(fn=cmd_task_heartbeat)

    tho = with_commit(tk.add_parser("handoff"))
    tho.add_argument("task")
    tho.add_argument("--agent", required=True)
    tho.add_argument("--note", required=True)
    tho.add_argument("--status", choices=TASK_STATUSES)
    tho.set_defaults(fn=cmd_task_handoff)

    td = with_commit(tk.add_parser("done"))
    td.add_argument("task")
    td.add_argument("--agent", required=True)
    td.add_argument("--note")
    td.set_defaults(fn=cmd_task_done)

    tt = with_commit(tk.add_parser("takeover"))
    tt.add_argument("task")
    tt.add_argument("--agent", required=True)
    tt.add_argument("--reason", required=True)
    tt.add_argument("--force", action="store_true", help="take over even if not stale")
    tt.set_defaults(fn=cmd_task_takeover)

    tl = tk.add_parser("list")
    tl.add_argument("--status", choices=TASK_STATUSES)
    tl.add_argument("--owner")
    tl.set_defaults(fn=cmd_task_list)

    lk = sub.add_parser("lock").add_subparsers(dest="lcmd", required=True)
    la = lk.add_parser("acquire")
    la.add_argument("lane", choices=LOCK_LANES)
    la.add_argument("--owner", required=True)
    la.add_argument("--ttl", type=int, default=60, help="minutes")
    la.add_argument("--note")
    la.set_defaults(fn=cmd_lock_acquire)
    lr = lk.add_parser("release")
    lr.add_argument("lane", choices=LOCK_LANES)
    lr.add_argument("--owner", required=True)
    lr.add_argument("--force", action="store_true")
    lr.set_defaults(fn=cmd_lock_release)
    lk.add_parser("status").set_defaults(fn=cmd_lock_status)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
