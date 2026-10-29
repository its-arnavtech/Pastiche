# 0005 CPU measurement, BS.1770 streaming and explicit Intel placement

Context: 500 tracks generated successfully in 639.16 seconds. The shared guards
landed during that first run. OpenVINO discovery exposes both Intel Arc GPU.0 and
NVIDIA GPU.1, so an unqualified vendor assumption would cross lane ownership.

Decision: all subsequent writers call remixer.guards plus a local disk-floor
check. Select/validate Intel GPUs by their reported full name before compilation;
never compile the NVIDIA device through this lane. Export a fixed, seeded MLP
directly to OpenVINO IR; label its weights synthetic and untrained. Check numeric
agreement with NumPy before timing. Record unsupported devices and CPU fallback
explicitly. Use one CPU inference thread.

For audio, use Pedalboard's Rubber Band time/pitch processing and pyloudnorm's
K-weighting filters. Compute continuous 400 ms / 100 ms loudness energies using
cumulative sums and BS.1770 absolute/relative gating; validate against the package
meter. Restarted the first full analysis at atomic checkpoints to apply this
optimization, with an algorithm-version bump so older features are not reused.
Benchmark CPU stages with forced processing, excluding pool warm-up, and preserve
every configuration. The knee is the fewest workers within 3% of the observed peak;
stop confirmation only after two rounds improve the previous best by <3%.

Alternatives: assume OpenVINO only enumerates Intel GPUs; use approximate RMS as
LUFS; count cached outputs as measured compute; infer P/E ordering by CPU number.

Consequences: Windows topology discovery stays in a read-only adapter. CPU-set
efficiency classes establish P/E affinity groups without machine-specific indices.
Full-budget sustains use unrestricted scheduling; affinity results remain separate.
CPU temperatures are unavailable unless the coordinator's sensor adapter supplies
them. Host telemetry includes other agents and is labeled accordingly. First-run
corpus measurements used the local disk guard before the shared module landed.

References:

- [Pedalboard time_stretch](https://spotify.github.io/pedalboard/reference/pedalboard.html#pedalboard.time_stretch)
- [pyloudnorm implementation](https://github.com/csteinmetz1/pyloudnorm/blob/master/pyloudnorm/meter.py)
- [OpenVINO Core](https://docs.openvino.ai/nightly/api/ie_python_api/_autosummary/openvino.Core.html)
- [Microsoft CPU-set efficiency classes](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_cpu_set_information)
