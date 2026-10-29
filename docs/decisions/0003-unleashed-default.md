# 0003 Unleashed mode is the default

- Context: the user owns a backup laptop and asked to find the hardware's own limit.
- Decision: `remixer.guards` logs thermals, battery state and throttle reasons but never acts on them. The only active floor: free disk < 10 GB pauses writers and purges caches inside the data dir. `--safe` restores conservative guards (disk 25 GB, pause on battery, reduce at GPU 90 C / CPU 100 C, hard pause at GPU 95 C / CPU 105 C). Firmware thermal protection remains the real limit.
- Alternatives: the spec's original watchdog (reduce at CPU 98 C / GPU 90 C).
- Consequences: throttling shows up in telemetry as clock drops and throttle reasons, which the peak report lists. Checkpointing after every unit bounds loss on a hard shutdown to one item.
