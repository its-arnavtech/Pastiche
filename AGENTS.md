# AGENTS.md: read this first

Single entry point for every AI agent working in this repo. Keep it under 150 lines.

## Project

StemDNA (codename, constant `PROJECT_NAME` in `src/remixer/__init__.py`; package dir `src/remixer/`).
A local, hardware-maxing audio pipeline: separate a music library into stems (Demucs), analyze and
embed them, learn the owner's taste, and assemble new tracks from recombined stems. POC 1 runs on one
Windows laptop and deliberately saturates GPU, CPU, NPU/iGPU, RAM and NVMe, then documents the
machine's peak. Standalone project: do not reference or reuse any other existing project.

- Build spec: `docs/specs/stemdna-poc1-local-max.md`. Context only: `docs/specs/stemdna-poc2-commercial.md`.
- Hardware and tool facts: `docs/ENVIRONMENT.md`. Things only the user can do: `docs/NEEDS_USER.md`.
- Tasks: `tasks/T-###_slug.md`. Changelog: `changelog/` (source) and `CHANGELOG.md` (generated).
- Decisions: `docs/decisions/NNNN-title.md`. Status flags: `docs/STATUS.md`. Peak results: `docs/PEAK_REPORT.md`.
- Lane budgets: `config/resources.yaml`. Runtime profile: `profile.yaml`.

## Agents and lanes

| Agent id | Where it runs | Branch | Owns |
|---|---|---|---|
| `opus-cc` | the laptop, Claude Code | `dev` | scaffold, coordination, core interfaces, GPU lane, telemetry, benchmarks, merging |
| `gpt-sol` | the laptop, same working tree | `dev` | CPU lane, NPU/iGPU lane, synthetic corpus, DSP, synth lab |
| `cursor-opus` | Cursor cloud (no access to this hardware) | `feature/skip-analytics` | event interpretation, skip heatmap, fatigue model, player UI, contract tests |

`opus-cc` is coordinator: it rebalances tasks, merges `feature/skip-analytics` into `dev` (`--no-ff`),
and only it or the user merges `dev` into `main`, and only when `dev` passes all tests.

## Rules (non-negotiable)

- Never stop to ask the user. Decide, write a short record in `docs/decisions/`, continue.
- Stop a line of work only for: money, missing credentials, or an irreversible action outside this repo.
  Record it in `docs/NEEDS_USER.md` and move on.
- Never touch BIOS, drivers, fan curves, overclock/undervolt. Never delete anything outside the repo and its data dir.
- The user's own music files are strictly read-only: never modify, move, upload or log their contents.
- Code against interfaces, never against this machine. Windows-specific calls live in adapters only.
- Windows: `pathlib` everywhere; multiprocessing uses `spawn`; every entry point behind `if __name__ == "__main__"`.
- Data dir is `data/` (gitignored), overridable with `REMIXER_DATA_DIR`.
- Synthetic or augmented rows carry `synthetic=true` / `augmented=true` and never mix with real taste data.
- Dependency changes go through `uv add`, committed alone with a changelog entry.
- Never silently rewrite another agent's completed work: open a task, or make a minimal change with a changelog entry.

## Git

- Two agents share one working tree on `dev`. Commit only the paths you changed: `git add <paths>`
  then `git commit -- <paths>` (or `git commit --only`). Never `git add -A` or `git add .`.
- Never `git stash`, `reset --hard`, `clean`, `checkout -- .`, force-push, or rewrite published history.
- Push `dev` after every milestone. `CHANGELOG.md` is generated: on conflict, run `agentctl changelog`.
  `uv.lock` conflicts: resolve `pyproject.toml`, then run `uv lock`.

## Start of session

1. Read this file.
2. `python scripts/agentctl.py status` (branch, open tasks, claims with heartbeat age, locks, last 15 changelog entries).
3. Read the changelog entries and task files relevant to what you are about to touch.
4. Claim a task (`agentctl task claim T-### --agent <id>`) or create one (`agentctl task new ...`).
5. Only then write code.

## End of a unit of work

1. Tests pass (`uv run pytest`).
2. Changelog entry written: `python scripts/agentctl.py log --agent <id> --type <type> --slug <slug> --tasks T-### --files <paths> --what ".." --why ".." --verify ".." --next ".."`.
3. Task file updated (status plus handoff notes: `agentctl task handoff|done`).
4. Commit your paths only. Push `dev` if it's a milestone.

## Tasks

One file per task, `tasks/T-###_slug.md`. Frontmatter: `id, title, status (todo|in_progress|blocked|review|done),
owner, branch, lane (gpu|cpu|npu|none), depends_on, owns_paths, claimed_at, heartbeat_at, priority`.
Body: Goal; Definition of done; Progress and handoff log (append-only, newest at bottom, timestamp + agent id).

- Claim only `todo` tasks via `agentctl task claim`, which commits the claim immediately.
- Heartbeat every 30 minutes while working: `agentctl task heartbeat T-### --agent <id> [--note ..]`.
- A claim with no heartbeat and no changelog entry from its owner for more than 2 hours is stale; anyone
  may `agentctl task takeover T-### --agent <id> --reason ".."` (logged as a `handoff` changelog entry).
- Anyone may open a new task to extend, review, or fix finished work.

## Changelog

One file per entry: `changelog/YYYYMMDD-HHMMSS_<agent>_<slug>.md`. Frontmatter `ts, agent, branch,
type (feat|fix|perf|docs|decision|handoff|blocker|bench|merge), tasks, files`. Body: What changed; Why;
How to verify; Next / handoff. `agentctl changelog` regenerates `CHANGELOG.md` (newest first). Never hand-edit it.

## Decisions

`docs/decisions/NNNN-title.md`: context, decision, alternatives, consequences. Short.

## Resource lanes and locks

`agentctl lock acquire <gpu|cpu|npu> --owner <id> --ttl <minutes> --note "<what>"`, `lock release <lane> --owner <id>`,
`lock status`. Lock files live in `.locks/` (gitignored); expired locks are free; re-acquire to extend.

- `gpu` is exclusive: 8 GB VRAM cannot be shared by two jobs.
- Lanes run concurrently with each other; that is how every engine gets saturated at once.
- Budgets come from the real core count (`config/resources.yaml`): GPU feeders 4 logical cores,
  reserve 1 logical core (OS and agent tooling), CPU lane gets the rest. Never reserve zero.
- The all-engines peak run acquires `gpu`, `cpu`, `npu` in that order.

## Run modes

Unleashed is the default (`remixer.guards`): thermals, battery and throttle reasons are logged, never acted
on. The only software floor: free disk < 10 GB pauses writers and purges caches inside the data dir.
`--safe` restores conservative guards. Checkpoint after every unit of work.
