# Environment facts

Recorded by `opus-cc` on 2026-10-29 (UTC). Re-run the commands below if hardware or drivers change.

## Machine

| Item | Value | Source |
|---|---|---|
| Model | ASUS Vivobook Pro 15 N6506MV | `Win32_ComputerSystem` |
| OS | Windows 11 Home 10.0.26300 | |
| CPU | Intel Core Ultra 9 185H, base 2.5 GHz | `Win32_Processor` |
| Physical cores | 16 (6 P, 8 E, 2 LP-E) | `NumberOfCores` |
| Logical processors | 22 | `NumberOfLogicalProcessors`, `nproc` |
| RAM | 25,095,254,016 bytes (23.4 GiB) | `TotalPhysicalMemory` |
| Disk C: free | 753 GB free, 1,293 GB used | `Get-PSDrive C` |
| dGPU | NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB, driver 610.74, CUDA UMD 13.3, WDDM | `nvidia-smi` |
| iGPU | Intel Arc Graphics, driver 32.0.101.6127 | `Win32_VideoController` |
| NPU | Intel AI Boost, status OK | `Get-PnpDevice` |
| Power | On AC (`BatteryStatus=2`), battery 98% | `Win32_Battery` |
| Power plan | Balanced, GUID `381b4222-f694-41f0-9685-ff5bb260df2e` (original, unchanged) | `powercfg /getactivescheme` |

`nvidia-smi` at idle showed 60 C, P0, and a nonsensical power reading (`590W / 102W`); the 102 W cap is
plausible, the 590 W draw is a driver reporting glitch at idle. Telemetry uses pynvml and logs what it gets.

## Toolchain

| Tool | Version |
|---|---|
| System Python | 3.10.11 (not used) |
| Project Python | 3.11.15 (uv-managed) |
| uv | 0.11.26 |
| git | 2.54.0.windows.1 |
| gh | logged in as `its-arnavtech` (scopes: repo, workflow, gist, read:org) |
| ffmpeg | 8.1.2 full_build (gyan.dev) |
| Remote | `origin` = https://github.com/its-arnavtech/Pastiche.git |

## PyTorch / CUDA

See the section appended after `uv sync` (T-001).

## Lane budget (from the counts above)

22 logical: GPU feeders 4, reserve 1, CPU lane 17. See `config/resources.yaml`.
