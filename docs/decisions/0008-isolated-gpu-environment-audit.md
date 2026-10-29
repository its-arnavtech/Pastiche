# Isolated GPU environment audit

## Context

gpt-audit was asked to diagnose idle NVIDIA activity and a Python launcher error while
opus-cc and gpt-sol actively use the shared `.venv` and GPU lease.

## Decision

Preserve the shared interpreter, dependencies, running processes and system settings.
Use a gitignored `.venv-audit` and scratch project under `data/audit/`; acquire the
GPU lease before CUDA smoke tests. Record fixes and coordinator handoff in
`docs/audits/gpu-env-audit.md` rather than change active dependency files.

## Alternatives

Recreate `.venv` or override the GPU lease. Both would disturb active work.

## Consequences

CUDA validation may wait for the current benchmark. No dependency change to the
main project is justified unless the audit demonstrates a defect.

## Abandoned lease recovery, 2026-10-29 04:22 UTC

The T-005 lease remained after its recorded PID 24332 and the embedding workers exited.
Two host checks five seconds apart found no recorded PID, no remixer CUDA workers,
no NVIDIA compute processes, and unchanged lease contents. Recover this exact
abandoned lease with `agentctl lock release gpu --owner gpt-audit --force` only
after repeating those conditions immediately before release. The already-waiting
audit probe then acquires its own lease. Do not reclaim a lease with a live owner,
active GPU worker, changed contents, or failed process/driver queries.

The recorded PID can be the short-lived acquisition CLI, rather than the lane
worker. PID absence alone is insufficient: this recovery was tied to the known
T-005 command and required its worker inventory and independent NVIDIA checks.
The audit subsequently held its own lease, passed matmul (100% GPU peak) and
synthetic pretrained Demucs on CUDA, and released that lease normally.
