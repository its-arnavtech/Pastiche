"""Isolated CUDA/Demucs smoke test; never loads CUDA without the GPU lease."""
from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--output", type=Path, default=Path("data/audit/gpu-probe.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    agentctl = root / "scripts/agentctl.py"
    deadline = time.monotonic() + args.wait_seconds
    last_notice = 0.0
    while True:
        acquired = subprocess.run(
            [sys.executable, str(agentctl), "lock", "acquire", "gpu", "--owner", "gpt-audit",
             "--ttl", "10", "--note", "isolated audit matmul and tiny synthetic Demucs"],
            cwd=root, capture_output=True, text=True,
        )
        if acquired.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise SystemExit(acquired.stdout + acquired.stderr)
        if time.monotonic() - last_notice >= 60:
            print("Waiting for GPU lease: " + (acquired.stdout + acquired.stderr).strip(), flush=True)
            last_notice = time.monotonic()
        time.sleep(min(5, max(0, deadline - time.monotonic())))

    samples: list[dict] = []
    stopped = threading.Event()
    phase = "startup"

    def sample() -> None:
        while not stopped.is_set():
            observed_phase = phase
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                 "--format=csv,noheader,nounits"], capture_output=True, text=True,
            )
            samples.append({"time": time.time(), "phase": observed_phase,
                            "returncode": result.returncode, "csv": result.stdout.strip(),
                            "error": result.stderr.strip()})
            stopped.wait(.5)

    monitor = threading.Thread(target=sample, daemon=True)
    report = {"synthetic": True, "python": sys.executable, "samples": samples}
    try:
        monitor.start()
        import torch
        import torchaudio

        torch.set_num_threads(2)
        report.update(torch=torch.__version__, torchaudio=torchaudio.__version__,
                      cuda=torch.version.cuda, cuda_available=torch.cuda.is_available())
        assert torch.cuda.is_available(), report
        report["device"] = torch.cuda.get_device_name(0)
        print(json.dumps({k: v for k, v in report.items() if k != "samples"}), flush=True)
        phase = "matmul"
        a = torch.randn(4096, 4096, dtype=torch.float16, device="cuda")
        b = torch.randn_like(a)
        c = torch.empty_like(a)
        iterations = 0
        start = time.monotonic()
        with torch.inference_mode():
            while time.monotonic() - start < args.seconds:
                for _ in range(32):
                    torch.mm(a, b, out=c)
                torch.cuda.synchronize()
                iterations += 32
        report["matmul"] = {"iterations": iterations, "seconds": time.monotonic() - start,
                            "finite": bool(torch.isfinite(c).all().item())}
        del a, b, c
        gc.collect()
        torch.cuda.empty_cache()
        phase = "demucs"
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        model = get_model("htdemucs").to("cuda").eval()
        # Synthetic stereo noise only; no library audio, catalog or queue access.
        audio = torch.randn(1, 2, model.samplerate, device="cuda") * .01
        start = time.monotonic()
        with torch.inference_mode():
            stems = apply_model(model, audio, device="cuda", shifts=0, split=True, progress=False)
        torch.cuda.synchronize()
        report["demucs"] = {"model": "htdemucs", "input_seconds": 1,
                            "shape": list(stems.shape), "device": str(stems.device),
                            "finite": bool(torch.isfinite(stems).all().item()),
                            "seconds": time.monotonic() - start}
        assert report["matmul"]["finite"] and report["demucs"]["finite"]
    except BaseException as exc:
        report["error"] = repr(exc)
        raise
    finally:
        stopped.set()
        if monitor.ident is not None:
            monitor.join(timeout=15)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        subprocess.run([sys.executable, str(agentctl), "lock", "release", "gpu",
                        "--owner", "gpt-audit"], cwd=root, check=True)
        print(json.dumps({k: v for k, v in report.items() if k != "samples"}), flush=True)


if __name__ == "__main__":
    main()
