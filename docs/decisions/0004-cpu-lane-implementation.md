# 0004 CPU lane implementation and ownership

Context: gpt-sol's assignment calls for 500 synthetic tracks and independent CPU/NPU
stages while opus-cc is still creating core interfaces. The task board uses
`corpus/`, `cpu/`, and `synth/`; the assignment also permits `tools/corpus/` and DSP.

Decision: implement reusable stages in the task board's owned paths, expose standalone
`python -m` entry points, and keep integration with the shared CLI minimal. Generate
500 seeded tracks by default, streaming bounded audio blocks to PCM16 WAV with true
stems and atomic per-track checkpoints plus a Parquet manifest. Use the configured
CPU lane budget, borrow one host thread when the NPU lane is active, and limit native
math threads to one per worker. Use the shared guards as soon as they land; the
standalone writer also checks the 10 GiB disk floor before allocating a track.

Alternatives: wait for all shared interfaces; allocate whole multi-minute tracks
in memory in every worker; add a second DSP dependency immediately.

Consequences: workers can start independently; bounded memory leaves room for GPU
feeders. Repeated seeds and recipes are byte reproducible within the recorded
implementation/dependency versions. Heuristic fitness is synthetic and cannot enter
real taste training. Hardware results will distinguish isolated and overlapping runs.
