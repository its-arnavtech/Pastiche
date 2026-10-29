"""Seeded synth genomes, replaceable fitness and checkpointed evolution."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Protocol

import numpy as np
import soundfile as sf

from remixer.corpus.generate import atomic_json
from remixer.cpu.runtime import LaneMonitor, configured_workers, guarded, process_pool


class FitnessScorer(Protocol):
    """Adapter point for a taste scorer; evaluation must be deterministic."""

    def score(self, audio: np.ndarray, sample_rate: int) -> float: ...


@dataclass(frozen=True)
class Genome:
    notes: tuple[int, ...]
    amplitudes: tuple[float, ...]
    harmonics: tuple[float, ...]
    bpm: float
    tonic: int
    minor: bool
    attack: float
    release: float

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, "notes": tuple(value["notes"]), "amplitudes": tuple(value["amplitudes"]),
                      "harmonics": tuple(value["harmonics"])})


def random_genome(rng: np.random.Generator) -> Genome:
    return Genome(tuple(map(int, rng.integers(0, 7, 16))), tuple(map(float, rng.uniform(.4, 1, 16))),
                  tuple(map(float, rng.uniform(.02, 1, 6))), float(rng.integers(80, 161)),
                  int(rng.integers(12)), bool(rng.integers(2)), float(rng.uniform(.002, .05)),
                  float(rng.uniform(.04, .2)))


def render_genome(genome: Genome, sample_rate: int = 22050, bars: int = 4) -> np.ndarray:
    if sample_rate < 2000 or bars < 1 or genome.bpm <= 0:
        raise ValueError("invalid synth rate, length or BPM")
    scale = np.array([0, 2, 3, 5, 7, 8, 10] if genome.minor else [0, 2, 4, 5, 7, 9, 11])
    seconds = bars * 4 * 60 / genome.bpm
    t = np.arange(round(seconds * sample_rate)) / sample_rate
    beat = t * genome.bpm / 60
    indices = (beat * 2).astype(int) % len(genome.notes)
    local = np.mod(beat * 2, 1) * 30 / genome.bpm
    degrees = np.asarray(genome.notes)[indices]
    midi = 60 + genome.tonic + scale[degrees % 7] + 12 * (degrees // 7)
    frequency = 440 * 2.0 ** ((midi - 69) / 12)
    envelope = (1 - np.exp(-local / genome.attack)) * np.exp(-local / genome.release)
    sound = np.zeros(len(t))
    for harmonic, amplitude in enumerate(genome.harmonics, 1):
        sound += amplitude * np.sin(2 * np.pi * frequency * harmonic * local)
    sound *= envelope * np.asarray(genome.amplitudes)[indices] / (sum(genome.harmonics) + 1e-8) * .7
    kick_time = np.mod(beat, 1) * 60 / genome.bpm
    sound += .15 * np.sin(2 * np.pi * 55 * kick_time) * np.exp(-kick_time * 25)
    return np.column_stack((sound, sound)).astype(np.float32)


class HeuristicScorer:
    """Spectral balance, pulse regularity, and chroma concentration only."""

    def score(self, audio: np.ndarray, sample_rate: int) -> float:
        mono = audio.mean(axis=1)
        n = min(32768, len(mono))
        spectrum = np.abs(np.fft.rfft(mono[:n] * np.hanning(n)))**2
        frequencies = np.fft.rfftfreq(n, 1 / sample_rate)
        total = spectrum.sum() + 1e-12
        bands = np.array([spectrum[(frequencies >= low) & (frequencies < high)].sum() / total
                          for low, high in ((40, 250), (250, 2000), (2000, 8000))])
        balance = float(np.exp(-np.linalg.norm(bands - [.2, .65, .15])))
        hop = max(1, sample_rate // 100)
        count = len(mono) // hop
        energy = np.sqrt(np.mean(mono[:count * hop].reshape(count, hop)**2, axis=1))
        novelty = np.maximum(0, np.diff(energy))
        from scipy.signal import fftconvolve
        autocorr = fftconvolve(novelty, novelty[::-1], mode="full")[len(novelty)-1:]
        pulse = float(np.max(autocorr[30:90]) / (autocorr[0] + 1e-12)) if len(autocorr) > 90 else 0
        valid = (frequencies > 100) & (frequencies < 5000)
        chroma = np.bincount(np.rint(69 + 12 * np.log2(frequencies[valid] / 440)).astype(int) % 12,
                             weights=spectrum[valid], minlength=12)
        from remixer.cpu.analyze import estimate_key
        coherence = max(0, estimate_key(chroma)[1])
        return float(.35 * balance + .3 * pulse + .35 * coherence)


def breed(left: Genome, right: Genome, rng: np.random.Generator) -> Genome:
    cut = int(rng.integers(1, len(left.notes)))
    notes = np.array(left.notes[:cut] + right.notes[cut:])
    changed = rng.random(len(notes)) < .15
    notes[changed] = rng.integers(0, 7, int(changed.sum()))
    harmonics = np.maximum(.01, np.array(left.harmonics) * .5 + np.array(right.harmonics) * .5 + rng.normal(0, .04, len(left.harmonics)))
    return Genome(tuple(map(int, notes)), left.amplitudes[:cut] + right.amplitudes[cut:],
                  tuple(map(float, harmonics)), left.bpm, left.tonic, left.minor,
                  float(np.clip((left.attack + right.attack) / 2 + rng.normal(0, .002), .001, .1)),
                  float(np.clip((left.release + right.release) / 2 + rng.normal(0, .005), .02, .5)))


def evaluate_genome(job):
    genome, sample_rate, scorer = job
    audio = render_genome(genome, sample_rate)
    return {"fitness": scorer.score(audio, sample_rate),
            "audio_hash": hashlib.sha256(audio.tobytes()).hexdigest(), "genome": asdict(genome)}


def evolve(destination: Path, *, generations: int = 10, seconds: float | None = None,
           population_size: int | None = None, workers: int | None = None, seed: int = 0,
           sample_rate: int = 22050, scorer: FitnessScorer | None = None, resume: bool = False) -> dict:
    workers = configured_workers(workers)
    population_size = population_size or workers * 2
    if population_size < 4 or generations < 1 or (seconds is not None and seconds <= 0):
        raise ValueError("population >= 4, generations and seconds positive required")
    scorer = scorer or HeuristicScorer()
    scorer_name = type(scorer).__module__ + "." + type(scorer).__qualname__
    rng = np.random.default_rng(seed)
    destination.mkdir(parents=True, exist_ok=True)
    checkpoint = destination / "population.json"
    population = [random_genome(rng) for _ in range(population_size)]
    history, generation = [], 0
    if resume and checkpoint.exists():
        saved = json.loads(checkpoint.read_text())
        if saved["scorer"] != scorer_name or saved["sample_rate"] != sample_rate:
            raise ValueError("resume scorer/sample rate must match checkpoint")
        rng.bit_generator.state = saved["rng_state"]
        population = [Genome.from_dict(value) for value in saved["population"]]
        population_size = len(population)
        generation, history = saved["generation"], saved["history"]
    started, clips, new_generations = time.perf_counter(), 0, 0
    with LaneMonitor() as monitor, process_pool(workers) as pool:
        while (time.perf_counter() - started < seconds) if seconds is not None else (new_generations < generations):
            guarded(destination)
            results = list(pool.map(evaluate_genome, ((genome, sample_rate, scorer) for genome in population)))
            results.sort(key=lambda row: (-row["fitness"], row["audio_hash"]))
            elites = [Genome.from_dict(row["genome"]) for row in results[:max(2, len(population)//4)]]
            population = [elites[0], elites[1]]
            while len(population) < population_size:
                a, b = rng.integers(len(elites), size=2)
                population.append(breed(elites[a], elites[b], rng))
            generation += 1
            new_generations += 1
            clips += len(results)
            history.append({"generation": generation, "best_fitness": results[0]["fitness"], "best_hash": results[0]["audio_hash"]})
            sf.write(destination / "best.wav", render_genome(elites[0], sample_rate), sample_rate, subtype="PCM_16")
            atomic_json(checkpoint, {"generation": generation, "population": [asdict(genome) for genome in population],
                                     "history": history, "rng_state": rng.bit_generator.state,
                                     "scorer": scorer_name, "sample_rate": sample_rate, "synthetic": True})
    elapsed = time.perf_counter() - started
    result = {"stage": "synth", "workers": workers, "generations": new_generations, "clips": clips,
              "wall_seconds": elapsed, "clips_per_minute": clips * 60 / elapsed,
              "generations_per_second": new_generations / elapsed, "synthetic": True,
              "scorer": scorer_name, "best_fitness": history[-1]["best_fitness"], **monitor.summary()}
    atomic_json(destination / "benchmark.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("REMIXER_DATA_DIR", "data")) / "synth")
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(evolve(args.output, generations=args.generations, seconds=args.seconds,
                            workers=args.workers, seed=args.seed, resume=args.resume), indent=2))


if __name__ == "__main__":
    main()
