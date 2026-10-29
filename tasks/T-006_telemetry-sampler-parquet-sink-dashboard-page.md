---
id: T-006
title: Telemetry sampler, Parquet sink, dashboard page
status: todo
owner: opus-cc
branch: dev
lane: none
depends_on: [T-001]
owns_paths: [src/remixer/telemetry/]
claimed_at:
heartbeat_at:
priority: P0
---

## Goal

1-2 s sampling of GPU (pynvml), per-core CPU, RAM, disk throughput, optional CPU temp, Intel iGPU/NPU via typeperf GPU Engine counters; Parquet sink; static HTML dashboard.

## Definition of done

`remixer telemetry run` writes Parquet; `remixer telemetry dashboard` renders HTML from it.

## Progress and handoff log

- 2026-10-29T02:29:55Z opus-cc: created (intended owner opus-cc)
