# 0030 The capped configuration becomes the default preset; uncapped needs `--unleashed`

- Context: decisions 0025/0026 found that this laptop sustains only the capped configuration; two uncapped runs ended in unexpected power-offs (System event 6008). Until now "unleashed" was the default and the caps lived behind `bench stress --cool`. The `--cool` watchdog cutoff for the CPU zone was 97 C, but the zone (ACPI `_TZ.THRM`) tops out at 95.9 C, so it could never fire.
- Decision:
  - New `remixer.presets` and a `stable:` block in `profile.yaml` define the default: 8 CPU render workers, light `htdemucs` only with batch up to 8 (heavy `htdemucs_ft` + shifts is replaced by the light model, with a warning), NPU only (no iGPU), thermal watchdog on (CPU zone 93 C, GPU 94 C on 10 s medians, resume 8 C lower, cool to 82 C between bench steps). `mode` defaults to `stable`.
  - The CPU cutoff is 93 C. It sits below the sensor maximum so it can fire.
  - The old behaviour is kept behind an explicit `--unleashed` (top-level and on `bench stress`; or `REMIXER_UNLEASHED=1`), which prints a warning naming the shutdowns. `bench stress --cool` stays as a no-op alias. `--safe` is unchanged.
  - `Guard` in stable mode raises a `reduce` signal when the 10 s median CPU zone reaches 93 C (a single boost spike does not trigger it); it falls back to the ACPI zone when LibreHardwareMonitor is absent.
  - PEAK_REPORT numbers are untouched; only a preset note was added (via `PEAK_NOTES.md`).
- Alternatives: leave unleashed as default with docs only (the shutdowns); drop the CPU cutoff (loses protection for non-bench lanes); make `profile.yaml` the only switch (an accidental edit could silently remove the caps).
- Consequences: the 93 C cutoff has not had its own sustained run (the benchmarks used 97 C and never fired); the report says so. Running `bench stress` now needs no flags to be safe. Anyone who wants the old peak must type `--unleashed`.
