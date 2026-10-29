# 0023 PR #2 / PR #3 merge: renumber the dev side

- Context: PR #2 (recipe planner) adds decisions 0018/0019 and tasks T-022..T-026; PR #3 (insight agents) adds decisions 0020/0021 and tasks T-027..T-029. Dev already held decision 0018 (opus-cc peak tuning rounds) and T-022 (gpt-sol's re-embed/retrain recovery task).
- Decision: renumber the two dev records instead of the PRs: decision 0018 -> 0022, T-022 -> T-030. References updated in the task file, two changelog entries, docs/reports/cpu-lane.md and tools/corpus/report.py. Commit messages that say T-022 for the recovery work (gpt-sol d05da63) are published history and stay as they are.
- Alternatives: renumber the PRs (43 files across both branches, and cursor's handoff notes and the user's backlog references to T-028/T-029 would shift).
- Consequences: the PR IDs merge unchanged; the recovery task is T-030.
