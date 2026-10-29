import pytest

from remixer.planner.scale import run_scale


def test_small_scale_run_is_clean():
    out = run_scale(n_stems=2_000, n_recipes=200, batch_size=50, seed=3)
    assert out["ban_leaks"] == 0 and out["patched_recipes"] > 0
    assert out["slot_fill_rate"] > 0.95
    assert out["rerender_sections"] + out["needs_regeneration_sections"] >= out["patched_recipes"]


@pytest.mark.scale
def test_ten_thousand_recipes_over_fifty_thousand_stems():
    out = run_scale(n_stems=50_000, n_recipes=10_000)
    print(out)
    assert out["stems"] > 49_000 and out["ban_leaks"] == 0
    assert out["slot_fill_rate"] > 0.99
    assert out["plan_s"] < 600 and out["patch_s"] < 30
