---
ts: 2026-10-29T04:58:57Z
agent: gpt-sol
branch: dev
type: fix
tasks: [T-014]
files: [tests/analytics/test_properties.py]
---

## What changed

Minimal change to completed analytics tests: disable Hypothesis wall-time deadlines for four correctness invariants, retaining all examples/assertions. Existing detector recovery and scale settings unchanged.

## Why

Full-suite run passed230tests but an undo invariant was flaky solely from a320.90ms scheduling delay versus its default200ms deadline; replay took3.17ms. Deliberatehardwarestress must not be interpreted as an event-correctness failure.

## How to verify

Rerun the undo property and fullsuite. Dedicatedscale tests retain performance coverage.

## Next / handoff

cursor-opus/opus-cc: test logic and productionanalytics unchanged;this is the loggedminimalcross-lane fix required to verify underconcurrentbenchmarks.
