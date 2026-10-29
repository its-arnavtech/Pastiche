# Needs the user

Things the agents deliberately did not do. Each item says why and the exact steps.

## 1. Power plan / performance mode (optional, for a higher peak)

The machine is on the **Balanced** plan (`381b4222-f694-41f0-9685-ff5bb260df2e`). `opus-cc` did not switch it:
changing OS power settings is a system-settings change it leaves to you (decision 0002). The peak report states
which plan was active during each run. To get the highest numbers, before a peak run:

1. ASUS: open MyASUS (or Armoury Crate) and select the **Performance / Full speed** fan and power profile.
2. Windows: Settings > System > Power & battery > Power mode > **Best performance**.
3. Optional, from an admin terminal: `powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c` (High performance).
   Restore afterwards with `powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e`.

Then tell any agent "rerun the peak" (or run `uv run remixer bench stress --ramp` yourself).
