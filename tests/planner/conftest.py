import pytest
from planner_helpers import library, make_planner

from remixer.planner import InMemoryRecipeStore, LineageIndex


@pytest.fixture
def lib():
    return library(400, seed=1)


@pytest.fixture
def world(lib):
    return make_planner(lib), InMemoryRecipeStore(), LineageIndex()
