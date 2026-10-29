from dataclasses import asdict

import numpy as np

from remixer.synth.lab import Genome, HeuristicScorer, breed, evaluate_genome, random_genome, render_genome


def test_synth_and_fitness_are_reproducible():
    rng = np.random.default_rng(9)
    genome = random_genome(rng)
    restored = Genome.from_dict(asdict(genome))
    np.testing.assert_array_equal(render_genome(genome, 8000), render_genome(restored, 8000))
    result = evaluate_genome((genome, 8000, HeuristicScorer()))
    assert np.isfinite(result["fitness"])
    assert 0 <= result["fitness"] <= 1
    assert result["audio_hash"] == evaluate_genome((genome, 8000, HeuristicScorer()))["audio_hash"]
    other = random_genome(rng)
    child = breed(genome, other, np.random.default_rng(42))
    assert child != genome
    assert child == breed(genome, other, np.random.default_rng(42))


def test_evolution_resume_matches_uninterrupted_generations(tmp_path):
    import json
    from remixer.synth.lab import evolve
    options = dict(population_size=4, workers=1, seed=2, sample_rate=8000)
    evolve(tmp_path / "whole", generations=2, **options)
    evolve(tmp_path / "resumed", generations=1, **options)
    evolve(tmp_path / "resumed", generations=1, resume=True, **options)
    whole = json.loads((tmp_path / "whole" / "population.json").read_text())
    resumed = json.loads((tmp_path / "resumed" / "population.json").read_text())
    assert whole["population"] == resumed["population"]
    assert whole["history"] == resumed["history"]
