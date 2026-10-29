"""Statistical attribution: which stems drive negative ratings (needs numpy, ``analytics`` extra).

Bayesian ridge regression of rating (+1 up, -1 down) on stem presence (or credit share), with an
unpenalized intercept. The prior precision ``lam`` is the ridge penalty, so the posterior mean is
the ridge solution and the posterior covariance ``sigma^2 (X'WX + lam I)^-1`` gives a standard
deviation per stem. A culprit is a stem whose coefficient is negative and at least ``min_z``
standard deviations below zero, seen in at least ``min_obs`` rated tracks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Observation:
    features: Mapping[str, float]  # stem id -> presence (1.0) or credit share
    rating: float                  # +1 thumbs up, -1 thumbs down
    weight: float = 1.0


@dataclass(frozen=True)
class Attribution:
    coef: dict[str, float]
    std: dict[str, float]
    support: dict[str, int]
    intercept: float
    n: int

    def z(self, stem: str) -> float:
        s = self.std.get(stem, 0.0)
        return self.coef.get(stem, 0.0) / s if s > 0 else 0.0

    def culprits(self, min_z: float = 2.0, min_obs: int = 3) -> list[str]:
        out = [k for k, c in self.coef.items()
               if c < 0 and self.support.get(k, 0) >= min_obs and self.z(k) <= -min_z]
        return sorted(out, key=lambda k: self.coef[k])


def fit_attribution(observations: Iterable[Observation], lam: float = 1.0) -> Attribution:
    import numpy as np

    obs = list(observations)
    stems = sorted({k for o in obs for k in o.features})
    if not obs or not stems:
        return Attribution({}, {}, {}, 0.0, len(obs))
    idx = {k: i for i, k in enumerate(stems)}
    n, p = len(obs), len(stems)
    X = np.zeros((n, p + 1))
    X[:, p] = 1.0
    for r, o in enumerate(obs):
        for k, v in o.features.items():
            X[r, idx[k]] = v
    y = np.array([o.rating for o in obs], dtype=float)
    w = np.array([o.weight for o in obs], dtype=float)
    penalty = np.full(p + 1, lam)
    penalty[p] = 1e-9
    A = X.T @ (X * w[:, None]) + np.diag(penalty)
    beta = np.linalg.solve(A, X.T @ (w * y))
    resid = y - X @ beta
    dof = max(1.0, w.sum() - min(p + 1, n))
    sigma2 = float((w * resid ** 2).sum() / dof) or 1e-6
    std = np.sqrt(np.clip(np.diag(np.linalg.inv(A)) * sigma2, 0, None))
    support = (X[:, :p] > 0).sum(axis=0)
    return Attribution(
        coef={k: float(beta[i]) for k, i in idx.items()},
        std={k: float(std[i]) for k, i in idx.items()},
        support={k: int(support[i]) for k, i in idx.items()},
        intercept=float(beta[p]), n=n,
    )
