---
ts: 2026-10-29T04:20:31Z
agent: gpt-sol
branch: dev
type: fix
tasks: [T-008, T-009, T-010, T-011, T-012, T-013]
files: [src/remixer/cpu/analyze.py, src/remixer/cpu/assemble.py, src/remixer/cpu/render.py, src/remixer/cpu/runtime.py, src/remixer/cpu/tuner.py, src/remixer/corpus, src/remixer/npu/scorer.py, src/remixer/synth/lab.py, tests/cpu, tests/npu, tools/corpus]
---

## What changed

Source provenance now follows selected recipe stems and every analysis/window/queue result; unknown sources never become real by default. All2500 original synthetic feature files retagged from their manifest. Benchmark timers exclude instrumentation startup and warm render/evolution workers; async timing guarantees a measured request under short deadlines. Windows atomic replacement retries, portable core reserve/feeder caps and versioned arrangement variety retain prior artifacts and seed reproducibility.

## Why

Meet strict synthetic/real separation and avoid startup-only microbenchmarks under deliberate full-system load.

## How to verify

Full repository suite76passed;focused CPU/NPU22passed,including provenance,queue,source-audio overwrite,tempo70-175anddelayed-instrumentation async checks. Originalcorpus key100%,BPMMAE0.275584;baseline retained.

## Next / handoff

Continue final evolution600s sustain and24varied-track integration;update finalreport and hand offCPU/NPUlocks toopus-ccT018. Budget-ceiling selections are explicitly distinguished from an observed worker plateau.
