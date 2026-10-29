# Needs the user

Things the agents deliberately did not do. Each item says why and the exact steps.

## 1. Power plan / performance mode (optional, for a higher peak)

**Status 2026-10-29: done for Windows.** The user set Settings > Power mode to Best performance on AC before the
T-018 run (docs/ENVIRONMENT.md). The ASUS fan/power profile (step 1 below) is not readable by the agents; if it is not
already on Performance / Full speed, it is the one remaining knob for a higher peak.

The machine is on the **Balanced** plan (`381b4222-f694-41f0-9685-ff5bb260df2e`). `opus-cc` did not switch it:
changing OS power settings is a system-settings change it leaves to you (decision 0002). The peak report states
which plan was active during each run. To get the highest numbers, before a peak run:

1. ASUS: open MyASUS (or Armoury Crate) and select the **Performance / Full speed** fan and power profile.
2. Windows: Settings > System > Power & battery > Power mode > **Best performance**.
3. Optional, from an admin terminal: `powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c` (High performance).
   Restore afterwards with `powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e`.

Then tell any agent "rerun the peak" (or run `uv run remixer bench stress --ramp` yourself).

## 2. Optional cleanup: merge worktree outside the repo

**Status 2026-10-29: done.** At the user's request opus-cc removed `C:\Pastiche-merge` with `git worktree remove` after the PR #2/#3 merge and deleted the local merge branches.

`opus-cc` merged PR #1 in a separate git worktree at `C:\Pastiche-merge` (branch `merge/skip-analytics`, already
fast-forwarded into `dev`) so conflict resolution never left the shared tree half-merged. It holds its own `.venv`
(several GB). Agents do not delete anything outside the repo, so remove it yourself when convenient:

```
git -C C:\Pastiche worktree remove --force C:\Pastiche-merge
git -C C:\Pastiche branch -d merge/skip-analytics
```

## 3. Shared `.venv` needs one `uv sync` after the agents stop

**Status 2026-10-29: done** (`uv sync --extra analytics` with all agents idle). Still open: browser tests need `uv sync --extra web-test` plus `uv run playwright install chromium`, which downloads a browser build from Microsoft's CDN; agents do not download browser binaries on their own.

The merge added dev/optional dependencies (hypothesis, playwright extra). Per the GPU audit, nobody re-syncs the shared
`.venv` while other agents' jobs run. When the machine is idle: `uv sync --extra analytics`. Then
`uv run pytest -m "not scale and not web"` runs the whole suite (212 tests passed in the merge worktree).
Browser tests additionally need `uv sync --extra web-test` and `uv run playwright install chromium`.
