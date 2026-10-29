# GPU and Python environment audit

Agent: `gpt-audit`; task: T-020; branch: `dev`; observations started
2026-10-28 22:54 America/Chicago (2026-10-29 UTC).

## Findings

1. The shared environment is **currently usable**, not missing its base Python.
   Its unquoted `home` exists, the base executable and venv launcher both return
   Python 3.11.15, and other agents have live processes using them. Do not repair,
   recreate, rename, or synchronize this environment while those jobs run.
2. The reported leading quote is **CPython launcher error formatting**, not
   evidence that `pyvenv.cfg` contains a quote. The launcher prepends a quote for
   its eventual command line, checks file attributes using the unquoted portion,
   and prints the partly constructed string if that check fails. An isolated
   missing-path reproduction below produces exactly this punctuation. A missing
   or inaccessible executable can trigger that branch. The original historical
   file-check failure cannot be reproduced now; its specific cause is unproven.
3. Neither the current project resolution nor installed torch is CPU-only.
   `pyproject.toml` already explicitly binds torch to `pytorch-cu130`, `uv.lock`
   selects the Windows `2.14.1+cu130` wheel, and installed `torch/version.py`
   reports CUDA 13.0. No CUDA-index fix to these files is needed.
4. NVIDIA idle snapshots coincide with no active CUDA context and benchmark
   startup/transition periods. They do not show CUDA being routed to Intel.
   Opus's subsequent controlled comparison identifies CPU saturation starving
   GPU feeders: its scheduling-priority adjustment recovered about 56x realtime.
   T-004 has already run Demucs; T-007 was actively benchmarking it. T-005
   embeddings was `todo` at the initial snapshot; Opus claimed it at 23:10:52
   local time and acquired a lease for its first run during this audit.
5. Intel load is expected T-012 OpenVINO work. Its live process and completed
   results name Intel Arc iGPU and Intel AI Boost, with no fallback. OpenVINO's
   `GPU.0` and CUDA's device 0 belong to separate enumerations.
6. The isolated hardware test passed: the RTX 4060 repeatedly reached 99–100%
   utilization during matmul, and pretrained Demucs produced finite CUDA stems.
   The NVIDIA driver and bundled CUDA runtime can execute real workloads.

The source explanation for the quote is
[CPython 3.11 PC/launcher.c, lines 1828–1855](https://github.com/python/cpython/blob/3.11/PC/launcher.c#L1828-L1855).
The explicit index/source configuration follows
[uv's PyTorch integration guide](https://docs.astral.sh/uv/guides/integration/pytorch/).

## Read-only evidence

Commands below were run from `C:\Pastiche`. Some process queries required the
normal host context because the restricted sandbox denied CIM access.

### Python and configuration

```powershell
Get-Content .venv\pyvenv.cfg
Get-Content .venv\pyvenv.cfg -Raw | Format-Hex
Get-ChildItem C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none
& .\.venv\Scripts\python.exe --version
& 'C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe' --version
```

```text
home = C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none
implementation = CPython
uv = 0.11.26
version_info = 3.11.15
include-system-site-packages = false
prompt = remixer
Python 3.11.15
Python 3.11.15
```

Hex bytes start `68 6F 6D 65 20 3D 20 43 3A` (`home = C:`), with no quote or
BOM. Base installation includes `python.exe` (91,648 bytes), `python311.dll`,
`Lib`, and `DLLs`. Windows `GetFileAttributesW` via `ctypes` returned `0x20`,
last error 0, for the base executable in this audit context. The shared config
SHA256 was `4297971651B85AF2B2FE109B719D93D5A269847B49133C74CE5F1ADACC32EFB2`.

A host NVIDIA process query also exposed the app-virtualized equivalent under
`AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\uv\python`.
Both that file and the normal Roaming executable exist now, are 91,648 bytes,
and share SHA256 `AE7E969410D751D010C2CA03394FE5C53230FBF48CA7D368B897E455ECA14FBA`.
This is reason to repeat checks in the failing application context; it is not
proof of the original failure's cause.

```powershell
& .\.venv\Scripts\python.exe -c 'import sys; print(sys.executable); print(sys.prefix); print(sys.base_prefix)'
```

```text
C:\Pastiche\.venv\Scripts\python.exe
C:\Pastiche\.venv
C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none
```

The first restricted `uv run --no-sync python --version` instead failed writing
uv interpreter-cache metadata under `AppData\Local\Packages\sandbox.{...}\AC\uv\cache`
with `Access is denied (os error 5)`. This is a separate, reproduced cache
permission failure. A process-local writable cache resolved it:

```powershell
$env:UV_CACHE_DIR = 'C:\Pastiche\data\audit\uv-cache'
uv run --no-sync python --version
# Python 3.11.15
```

This sets no persistent system setting and does not synchronize dependencies.

### Safe reproduction of misleading quote

Only a copied launcher and scratch config were changed:

```powershell
New-Item -ItemType Directory -Force data/audit/launcher-missing/Scripts
Copy-Item .venv/Scripts/python.exe data/audit/launcher-missing/Scripts/python.exe
Set-Content data/audit/launcher-missing/pyvenv.cfg 'home = C:\Pastiche\data\audit\nonexistent-python' -Encoding utf8NoBOM
& .\data\audit\launcher-missing\Scripts\python.exe --version
```

```text
No Python at '"C:\Pastiche\data\audit\nonexistent-python\python.exe'
```

### Live environment users

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python|uv.exe' } |
  Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine
```

Representative observed processes (PIDs are snapshots, not stable identifiers):

| Venv launcher PID | Base interpreter PID | Command |
|---|---|---|
| 22180 | 19684 | `tools/corpus/peak_run.py`, plus many spawn workers |
| 21908 | 22008 | `tools/corpus/variety_validation.py` |
| 21796 | 43792 | `tools/corpus/intel_peak_hold.py` |
| 14556 | 3496 | `remixer bench stress --ramp --lanes gpu --step-seconds 90s` |
| 11188 | 11364 | `-m remixer.cli separate --batch 5 --duration 90.0 --corpus-cycle` |
| 53436 | 42564 | `tools/corpus/gpu_overlap.py` |
| 43284 | 42124 | `pytest --tb=short` |

The venv launchers were under `C:\Pastiche\.venv\Scripts\python.exe` and their
base child interpreters under the exact uv-managed path above. Repair is unsafe
while these processes and their descendants remain.

### Driver and packages

```powershell
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
rg -n 'torch|index|cuda|pytorch' pyproject.toml uv.lock
Get-Content .venv\Lib\site-packages\torch\version.py
```

```text
NVIDIA GeForce RTX 4060 Laptop GPU
Driver / KMD: 610.74; CUDA UMD: 13.3; WDDM; 8188 MiB VRAM
22:55:23: GPU 0%, memory 0 MiB, no running GPU processes
Later: GPU 0%, memory 825 MiB, compute PID 11364
Later: GPU 0%, memory 4327 MiB (model/context present)
torch __version__ = '2.14.1+cu130'; cuda = '13.0'
```

The restricted GPU process query sometimes returned `[Insufficient Permissions]`
for process name and `[N/A]` for per-process WDDM memory; PID matching against the
host process inventory identified the Demucs worker. Empty/zero idle readings
alone cannot prove driver failure. Driver-supported CUDA UMD version and torch's
bundled CUDA version are different values; they need not be identical.

`uv.lock` torch record: version `2.14.1+cu130`, registry
`https://download.pytorch.org/whl/cu130`, wheel
`torch-2.14.1%2Bcu130-cp311-cp311-win_amd64.whl`.
The dependency/index setup already exists in commit `be93d8e`.

Torchaudio is absent from the main environment and lockfile. Demucs 4.1.0's
installed metadata only requires torchaudio for its optional training extra, so
its absence does not explain the current inference lane's idleness.

### Task, benchmark and Intel evidence

Read `tasks/T-004*`, `T-005*`, `T-007*`, `T-012*` and changelog entries
`20261029-030006`, `032006`, `032824`, `035027`.

* T-004 in progress: separation implementation landed; prior changelog reports
  htdemucs fp16 about 51x realtime at batch 10 (historical claim, not this audit's measurement).
* T-005 initially todo: no embedding execution expected at that point. It was
  subsequently claimed at 04:10:52 UTC and the first embedding run acquired the
  GPU lease at 04:11:15 UTC. This repository changed during the audit.
* T-007 active: `reports/peak/20261028-225051/steps.json` recorded successful
  25%, 50%, 75%, and 100% GPU ramp steps with 6.94x, 11.44x, 9.57x, and
  30.92x steady separation.
  Logs show repeated HF model checks, startup, and finite duration workers.
  For the 50% step, process wall span was about 242 s while reported lane wall
  time was 123.5 s. Startup/teardown and scheduling contention are material;
  the GPU is not continuously fed for the whole benchmark wall span.
* `src/remixer/gpu/separate.py` defaults `DemucsRunner(device='cuda')` and moves
  models and tensors there; it does not silently select OpenVINO or Intel.
* The initial GPU lease belonged to `opus-cc`, PID 3496, for the ramp. It was
  followed by a priority experiment lease and then the T-005 first-run lease,
  expiring 04:51:15 UTC. The audit does not override these leases. CPU and NPU
  leases belong to `gpt-sol`.
* `tools/corpus/intel_peak_hold.py` calls `benchmark_async` for `NPU` and `GPU.0`
  until the CPU peak completes. It was running as base Python PID 43792.
* `data/npu/dual/benchmark.json` reports 600 s results: `Intel(R) AI Boost`
  145476.69 inferences/s and `Intel(R) Arc(TM) Graphics (iGPU)` 92173.74
  inferences/s, both `fallback_reason: null`.
* `src/remixer/npu/scorer.py` verifies Intel vendor identity and rejects NVIDIA
  for this lane. These results and the live process explain sustained Intel
  compute load. This is process/artifact attribution, not a per-process Windows
  GPU Engine counter measurement of the user's earlier 100% screenshot.

The completed ramp `summary.json` contains 947 samples: NVIDIA mean utilization
11.76%, median 0%, fraction at least 90% utilization 0.057; CPU mean 90.89%;
Intel iGPU mean 89.44%, maximum 100%. Peak VRAM was 5.1 GiB, RAM 21.89 GiB,
swap 1.9 GiB, and NVIDIA temperature 91 C. These are the existing benchmark's
aggregate measurements, including startup, teardown and gaps. They demonstrate
intermittent CUDA work alongside sustained Intel work. Host scheduling and
memory pressure are plausible contributors to the idle fraction; the audit
does not claim to isolate their individual causal effects. The 590 W maximum
power reading is a known idle reporting anomaly, not credible laptop power draw.

During the audit, Opus committed its own fix and evidence in
`changelog/20261029-041049_opus-cc_gpu-priority-embed.md` and decision
`0012-gpu-lane-process-priority.md`: CPU sustain collapsed the isolated GPU ramp
to 8–24% average GPU utilization; with its process-priority boost, the same
separation load reached about 56x realtime. Its adapter now implements
`prioritize_current_process('gpu')`, called by separation and embedding commands.
This is stronger evidence of feeder scheduling starvation than an idle snapshot.
These changes were made by Opus concurrently, not by this audit; do not duplicate
or overwrite them. Other unisolated contributors, including memory pressure,
are not independently quantified here.

## Isolated validation

The scratch project is `data/audit/project`, with environment `.venv-audit`;
both are gitignored. Its dependencies are added with `uv add`, never into the
main project. `UV_PROJECT_ENVIRONMENT` is set only in those command processes.
The reproducible test is `tools/audit/gpu_probe.py`: acquire the GPU lease,
sample `nvidia-smi`, run fp16 4096-square matmuls, then pretrained htdemucs on
one second of generated stereo noise. No user's music, catalog or queue is read.

Install commands used (after creating a minimal Python 3.11 scratch project and
restricting its `tool.uv.environments` to Windows AMD64):

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'C:\Pastiche\.venv-audit'
uv add --project data/audit/project --python 'C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe' torch torchaudio --index 'pytorch-cu130=https://download.pytorch.org/whl/cu130'
# Set explicit = true on the scratch project's pytorch-cu130 index.
uv add --project data/audit/project --editable 'C:\Pastiche'
uv add --project data/audit/project pytest
```

The index resolved torch `2.14.1+cu130` and torchaudio `2.11.0+cu130`.
Both import successfully; matching version numbers were not assumed. The initial
exact `torchaudio==2.14.1` request was unsatisfiable and was not applied. The
scratch root needed its own supported-environment restriction: without it, uv's
universal resolution correctly rejects the main project's NumPy constraint
against Demucs's Intel-macOS-only `numpy<2` requirement. This is not a Windows
runtime problem or a reason to change the main project's existing restrictions.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:OPENBLAS_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
$env:UV_CACHE_DIR = 'C:\Pastiche\data\audit\uv-cache'
uv run --project data/audit/project --no-sync pytest -q
$env:HF_HOME = 'C:\Pastiche\data\audit\huggingface'
$env:TORCH_HOME = 'C:\Pastiche\data\audit\torch'
& .\.venv-audit\Scripts\python.exe tools/audit/gpu_probe.py --wait-seconds 1800
```

The full repository suite completed successfully (76 tests, exit 0, 100%) using
`uv run --project data/audit/project --no-sync pytest -q`. The isolated import
check reports `2.14.1+cu130 13.0 2.11.0+cu130` for torch, CUDA and torchaudio.
Hardware validation completed successfully under the audit's own GPU lease.

At 04:22 UTC the embedding worker had exited but its lease remained. Two host
queries five seconds apart found the recorded lease PID 24332 absent, no separation/embedding
or bench worker, no NVIDIA compute process, and identical lease contents.
Immediately rechecking those conditions allowed recovery of that exact orphaned
repo lease with `agentctl lock release gpu --owner gpt-audit --force` (output:
`gpu lock released`). The waiting probe then acquires its own lease; no live
process is interrupted. The recovery rule is recorded in decision 0008.

The lease's `pid` can identify a short-lived `agentctl` acquisition process, so
PID absence alone does **not** prove a lease is abandoned. Recovery here was
specific to the known T-005 run and also required the independent worker and
NVIDIA checks; do not generalize it to active leases.

At 04:23:19 UTC the probe acquired `gpu` as `gpt-audit`, ran the requested
workloads, and released it normally. Key output:

```text
python: C:\Pastiche\.venv-audit\Scripts\python.exe
torch: 2.14.1+cu130
torchaudio: 2.11.0+cu130
torch.version.cuda: 13.0
torch.cuda.is_available(): True
device: NVIDIA GeForce RTX 4060 Laptop GPU
matmul: 3776 iterations, 20.078 seconds, finite=True
Demucs: htdemucs, synthetic input 1 second, shape [1, 4, 2, 44100]
Demucs output device: cuda:0; finite=True; apply_model time 1.578 seconds
exit code: 0
```

The sampler recorded 69 `nvidia-smi` samples. Representative matmul CSV rows
(`utilization.gpu [%], memory.used [MiB], temperature.gpu [C]`):

```text
100, 217, 84
100, 217, 86
99, 217, 86
100, 217, 87
```

Peak matmul utilization was 100%; peak sampled temperature was 88 C. The tiny
Demucs call deliberately does not saturate the device for long; its CUDA output
and finite stems verify the model path, while the sustained matmul establishes
high utilization. The Demucs phase includes model download/loading, so its
phase average is not a steady inference utilization measure. Raw samples and
results remain at `data/audit/gpu-probe.json`. Public-model cache warnings about
Windows symlinks and unauthenticated HF downloads did not prevent completion;
no credentials or system-setting changes were needed.

The shared `pyvenv.cfg` SHA256 remained unchanged after validation. Neither
`pyproject.toml` nor `uv.lock` was modified by this audit, and `.venv` was not
repaired because active agents were using it.

## Minimal fix / coordinator handoff

**opus-cc: retain the current CUDA torch source mapping. Do not reinstall torch,
rewrite `pyvenv.cfg`, or recreate `.venv` on the evidence above.** For the
reproduced restricted-cache failure, the process-local `UV_CACHE_DIR` command
above is sufficient. For the earlier `No Python at` error, first repeat the base
file check and launcher command in the failing execution context; do not remove
an alleged quote that is not present in the file.

Keep Opus's concurrently landed scheduling adapter fix and throughput-based
VRAM sizing (decisions 0010 and 0012); validate sustained utilization with both
Intel/CPU lanes active. No driver, fan, power-plan or CUDA control-panel change
is required by this audit. Separate model download/startup time from steady
work when reporting GPU utilization.

Required CUDA index settings (already present):

```toml
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cu130" }
```

If an actual feature later requires torchaudio, first validate an available
compatible wheel; add `torchaudio = { index = "pytorch-cu130" }` alongside torch
and add the dependency with `uv add`. `torchaudio==2.14.1` was not available
on this index during the audit, so blindly pinning it to torch's version fails.
Keep such a dependency change in its own commit with its own changelog.

### Conditional repair only after all agents finish

1. Allow the agents and benchmarks to finish normally. Re-run the process query
   above; check command lines as well as paths, because base Python children of a
   venv are outside `.venv`. Check `python scripts/agentctl.py lock status`.
   If any repo worker/descendant or active lease remains, defer repair.
2. Check the real base path and launchers. If both work, no repair is needed:

   ```powershell
   Set-Location C:\Pastiche
   $env:UV_CACHE_DIR = 'C:\Pastiche\data\audit\uv-cache'
   Test-Path 'C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe'
   & 'C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe' --version
   & .\.venv\Scripts\python.exe --version
   uv run --no-sync python --version
   ```

3. Only if the base installation is genuinely missing/broken, reinstall that
   interpreter after all users have stopped, then recheck the launcher:

   ```powershell
   uv python install 3.11.15 --reinstall
   & .\.venv\Scripts\python.exe --version
   ```

4. If the base is healthy but the venv launcher/config is still broken, preserve
   the old environment and create a replacement **only after the idle gate**:

   ```powershell
   $auditBackupName = '.venv.pre-audit-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
   Rename-Item -LiteralPath 'C:\Pastiche\.venv' -NewName $auditBackupName
   uv venv .venv --python 'C:\Users\Arnav\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe'
   uv sync --locked
   uv run --no-sync python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())'
   uv run --no-sync pytest
   ```

   These conditional commands were **not run** by the audit. No deletion is
   required. Retain the backup until the coordinator verifies the replacement.

## Scope and preservation

No shared venv, main dependency files, agents' processes, hardware configuration,
drivers, power settings or fan settings were changed. No music files were
inspected. Scratch launcher files, install project and raw audit results are
under `data/audit`; only audit documentation, the smoke-test script, task,
decision, ignore rule and changelog are intended for commit.
