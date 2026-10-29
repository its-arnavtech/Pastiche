# 0002 Power plan left on Balanced

- Context: the brief allows switching the Windows power plan with `powercfg` for the peak hunt.
- Decision: `opus-cc` does not change OS power settings itself. Runs use the current plan (Balanced), the plan is recorded in every report, and `docs/NEEDS_USER.md` gives the user the exact commands (and the ASUS performance profile) for a higher peak.
- Alternatives: switch with `powercfg /setactive` and restore afterwards.
- Consequences: peak numbers may be below the hardware's absolute best; the report flags this, and a rerun after the user switches modes is one command.
