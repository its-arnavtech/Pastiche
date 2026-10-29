"""Stretch (T-019): MusicGen-small inference loop as extra GPU load.

Generates short clips from seeded text prompts in fp16 and discards them (pure load; nothing is
stored as content). Weights are CC-BY-NC-4.0 (docs/licenses.md): local, non-commercial
benchmarking only; never part of the commercial profile.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("remixer.gpu.musicgen")
MODEL = "facebook/musicgen-small"
PROMPTS = ["warm lo-fi drums with mellow bass", "bright synth arpeggio over a four on the floor beat",
           "slow ambient pads with soft piano", "funky bass line with tight hi-hats",
           "cinematic strings with deep percussion", "minimal techno groove with clicks"]


def run(duration_s: float = 300, batch: int = 8, tokens: int = 256, seed: int = 0, adapters=None) -> dict:
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    dev = "cuda"
    proc = AutoProcessor.from_pretrained(MODEL)
    model = MusicgenForConditionalGeneration.from_pretrained(MODEL, torch_dtype=torch.float16).to(dev).eval()
    sr = model.config.audio_encoder.sampling_rate
    frame_rate = model.config.audio_encoder.frame_rate
    g = torch.Generator(device=dev).manual_seed(seed)
    t0, clips, audio_s, rounds = time.perf_counter(), 0, 0.0, 0
    while time.perf_counter() - t0 < duration_s:
        prompts = [PROMPTS[(rounds * batch + i) % len(PROMPTS)] for i in range(batch)]
        inputs = proc(text=prompts, padding=True, return_tensors="pt").to(dev)
        torch.manual_seed(seed + rounds)
        with torch.inference_mode():
            out = model.generate(**inputs, do_sample=True, max_new_tokens=tokens, guidance_scale=3.0)
        torch.cuda.synchronize()
        clips += out.shape[0]
        audio_s += out.shape[0] * out.shape[-1] / sr
        rounds += 1
        log.info("musicgen: %d clips, %.1f audio-s generated, %.2f audio-s/s", clips, audio_s,
                 audio_s / (time.perf_counter() - t0))
    wall = time.perf_counter() - t0
    res = {"stage": "musicgen", "model": MODEL, "license": "CC-BY-NC-4.0", "batch": batch, "tokens": tokens,
           "clips": clips, "generated_audio_s": round(audio_s, 1), "wall_s": round(wall, 1),
           "audio_s_per_s": round(audio_s / wall, 3), "tokens_per_s": round(clips * tokens / wall, 1),
           "frame_rate": frame_rate, "vram_peak_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
           "synthetic": True}
    if adapters is not None:
        adapters.events.append("stage_metrics", [{"ts": time.time(), **res}])
    return res
