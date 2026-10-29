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

**Status 2026-10-29: done.** `uv sync --extra analytics --extra web-test --extra player` with all agents idle. The browser tests now run on the system Microsoft Edge when Playwright's own Chromium build is missing (decision 0029), so nothing is required. Optional: `uv run playwright install chromium` (a download from Microsoft's CDN) makes them use the bundled headless build instead.

The merge added dev/optional dependencies (hypothesis, playwright extra). Per the GPU audit, nobody re-syncs the shared
`.venv` while other agents' jobs run. When the machine is idle: `uv sync --extra analytics`. Then
`uv run pytest -m "not scale and not web"` runs the whole suite (212 tests passed in the merge worktree).
Browser tests additionally need `uv sync --extra web-test` and `uv run playwright install chromium`.

## 4. The laptop powered off twice under the T-018 load (Best performance mode)

Windows logged two unexpected shutdowns (System log, event 6008) during the first two T-018 attempts, both when the
CPU render lane started after the GPU ramp. The CPU package zone sits at ~79 C idle and reaches 96 C within seconds
under load. The agents now run with load caps and a thermal watchdog (decision 0025), but the cause is hardware/firmware
side and only you can act on it:

1. Check the ASUS fan profile (MyASUS / Armoury Crate) is on Performance or Full speed, not Silent/Standard.
2. Keep the vents clear and the laptop on a hard surface; consider a cooling pad.
3. Make sure the original (full-wattage) charger is connected; a lower-wattage USB-C charger cannot carry CPU + GPU peaks.
4. If shutdowns continue, switching Settings > Power mode back to Balanced made round 1 (60-minute sustain) stable.

## 5. Schedule the nightly insight job (optional)

`remixer insights nightly` runs the insight pass once per local night (after 03:00, decision 0028). Agents do not
register Windows scheduled tasks. To schedule it, run once in a terminal (Ollama must be running at that hour; the
Ollama tray app starts it at login):

```
schtasks /Create /SC DAILY /ST 03:30 /TN "Pastiche insights nightly" /TR "cmd /c cd /d C:\Pastiche && uv run --no-sync remixer insights nightly"
```

The profile uses `qwen3:4b`, which is already pulled. It garbles window ids in about half its analyst/skeptic replies
(the pipeline falls back safely); `ollama pull llama3.1:8b` and setting `llm.model` in `profile.yaml` should do better.

## 6. After the POC 1 wrap-up: decisions and actions only you can take (2026-10-29)

Nothing here blocks anything that was built. In rough order of value:

1. **Run it on real music (S).** `uv run remixer ingest --library "<a small folder>"`, then `remixer separate`, `analyze`, `embed`. The folder is read in
   place and never modified (`tests/test_real_use_path.py` proves it on read-only files). Nobody has heard Demucs or the planner on a real library yet.
2. **Pick the legal path (decision, no cost).** `docs/legal-paths.md` lays out on-device, cleared catalogs and direct licensing. Nothing commercial can start
   before this, and it needs a qualified reviewer. It is not legal advice.
3. **Resolve the GPL pieces for any distributed or client-side build.** `pedalboard` is GPL-3.0 and brings Rubber Band, which is GPL or paid
   (`docs/licenses.md`). Server-side only use is the lower-risk reading, which a lawyer should confirm.
4. **Schedule the nightly insight job** (item 5 above) and, if you want better insights, `ollama pull qwen3:8b` (Apache-2.0, about 5 GB; it cannot share
   the GPU with Demucs, so run it at night; `docs/KNOWN_LIMITATIONS.md` item 2). Both are your call: one is a persistent system change, one is a download.
5. **Optional: one 60-minute sustain under the stable preset** (`uv run remixer bench stress --sustain 60m`) to give the final configuration and the 93 C
   cutoff the sustain they never had. Only on AC power with clear vents; the stable preset caps itself. No agent will run it without being asked.
6. **Optional: `uv run playwright install chromium`** (about 150 MB from Microsoft's CDN) so the browser tests stop depending on the installed Edge.
7. **Cooling (item 4 above)** is still the only way to raise the CPU-and-GPU-together ceiling.
8. **Published:** `main` (merge commit `b3ee585`), `dev` and the tag `v0.1-poc1` were pushed to `origin` as asked. Nothing else was published.
9. **Delete the merged branches (S).** The wrap-up agent tried and the permission system refused branch deletion, so it did not retry. All four are already contained in `dev` and `main`; the tips are recorded so nothing is lost. Run:

   ```
   git branch -d feature/skip-analytics                       # local, was 7bc0c40
   git push origin --delete cursor/insight-agents-442b        # was 5e47ccc
   git push origin --delete feature/recipe-planner            # was 7056049
   git push origin --delete feature/skip-analytics            # was 8edf0ac
   ```

   There are no leftover git worktrees (`git worktree list` shows only `C:/Pastiche`). `.venv-audit/` (the GPU audit's separate virtual environment, git-ignored)
   was left alone; delete it if you do not need it.
