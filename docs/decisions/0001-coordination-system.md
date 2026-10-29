# 0001 Coordination system: per-file tasks and changelog, local lock files

- Context: three agents (two in one working tree on `dev`, one in Cursor cloud on `feature/skip-analytics`) with no real-time channel.
- Decision: one file per task (`tasks/`) and per changelog entry (`changelog/`) so branches never conflict on a shared file; `CHANGELOG.md` is generated. Resource locks are JSON files in gitignored `.locks/` with a TTL, created atomically (hard link), because only agents on this laptop compete for hardware. `scripts/agentctl.py` is stdlib-only so any agent can run it with any Python 3.10+.
- Alternatives: a shared `TASKS.md` (merge conflicts on every claim); GitHub issues (needs network, invisible to offline tools); SQLite (binary, unmergeable).
- Consequences: claims are committed immediately and only the task file is committed (`git commit --only`), so another agent's staged work is never swept in. Cursor sees claims only after `dev` is pushed.
