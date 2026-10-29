"""Taste model training loop (GPU lane, T-017).

Until the owner rates anything, the trainer learns from *synthetic* ratings: a hidden taste
direction in CLAP space plus noise decides thumbs up / down for a random subset of windows.
Synthetic and real ratings never meet: `load_ratings(kind)` returns exactly one kind and the
trainer refuses a mixed set. Synthetic ratings live in the `synthetic_ratings` event stream and
are flagged synthetic=1 in every row; real ratings come only from `rating_events` with synthetic=0.

The default network matches the NPU scorer shape (512 -> 256 -> 64 -> 1) so the weights can be
handed to the OpenVINO lane; `--width` scales it up purely as GPU load.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("remixer.gpu.taste")
VERSION = "taste-mlp-v1"


def load_window_vectors(adapters, model_version: str) -> tuple[list[str], np.ndarray]:
    """(window_ids, vectors float16 (n, d)) from the per-stem .npy checkpoints and the catalog."""
    root = adapters.profile.data_dir / "embeddings" / model_version.replace("@", "_").replace("/", "_")
    rows = adapters.catalog.query(
        "SELECT owner_id AS stem_id, window_id, start_ms FROM windows WHERE model_version=? ORDER BY owner_id, start_ms",
        (model_version,))
    by_stem: dict[str, list[str]] = {}
    for r in rows:
        by_stem.setdefault(r["stem_id"], []).append(r["window_id"])
    ids, vecs = [], []
    for stem_id, wids in by_stem.items():
        p = root / f"{stem_id}.npy"
        if not p.exists():
            continue
        v = np.load(p)
        if len(v) != len(wids):
            continue
        if not np.isfinite(v).all():
            raise ValueError("nonfinite CLAP checkpoint: re-embed with the fp32 log-mel version before training")
        ids.extend(wids)
        vecs.append(v)
    return ids, (np.concatenate(vecs) if vecs else np.zeros((0, 512), np.float16))


def synthesize_ratings(adapters, ids: list[str], vecs: np.ndarray, frac: float = 0.3, seed: int = 0,
                       sharpness: float = 12.0) -> dict:
    """Plant a hidden taste direction and sample ratings for `frac` of windows. All rows synthetic=1."""
    rng = np.random.default_rng(seed)
    d = vecs.shape[1]
    direction = rng.standard_normal(d).astype(np.float32)
    direction /= np.linalg.norm(direction)
    x = vecs.astype(np.float32)
    score = x @ direction
    score = (score - score.mean()) / (score.std() or 1.0)
    p_up = 1 / (1 + np.exp(-sharpness * score / 4))
    pick = rng.random(len(ids)) < frac
    up = rng.random(len(ids)) < p_up
    now = time.time()
    events = [{"event_id": f"syn-{seed}-{ids[i]}", "target_kind": "window", "target_id": ids[i],
               "rating": "up" if up[i] else "down", "wall_time": now, "synthetic": True, "seed": seed}
              for i in np.flatnonzero(pick)]
    adapters.events.append("synthetic_ratings", events)
    truth = adapters.profile.data_dir / "state" / f"synthetic_taste_seed{seed}.npy"
    truth.parent.mkdir(parents=True, exist_ok=True)
    np.save(truth, direction)
    return {"ratings": len(events), "up_frac": float(np.mean([e["rating"] == "up" for e in events])) if events else 0}


def load_ratings(adapters, kind: str) -> list[dict]:
    if kind == "synthetic":
        rows = adapters.events.read("synthetic_ratings")
        assert all(bool(r.get("synthetic")) for r in rows), "non-synthetic row in synthetic_ratings"
        return rows
    if kind == "real":
        rows = adapters.catalog.query("SELECT * FROM rating_events WHERE synthetic=0 AND target_kind='window'")
        assert not any(r.get("synthetic") for r in rows)
        return rows
    raise ValueError(kind)


def set_aside_superseded(out: Path, model_version: str) -> Path | None:
    """Keep a checkpoint trained on another embedding version for diagnosis instead of overwriting it."""
    import torch

    if not out.exists():
        return None
    try:
        prev = torch.load(out, map_location="cpu", weights_only=True).get("embedding_model")
    except Exception:
        prev = "unreadable"
    if prev == model_version:
        return None
    tag = str(prev).replace("@", "_").replace("/", "_")
    kept = out.with_name(f"{out.stem}.superseded-{tag}.pt")
    out.replace(kept)
    if out.with_suffix(".npz").exists():
        out.with_suffix(".npz").replace(kept.with_suffix(".npz"))
    log.warning("kept checkpoint trained on %s as %s", prev, kept.name)
    return kept


@dataclass
class TrainResult:
    kind: str
    n_train: int
    n_val: int
    epochs: int
    samples_per_s: float
    val_auc: float
    val_acc: float
    truth_cos: float | None
    path: str
    wall_s: float


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    order = np.argsort(scores)
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    pos = labels == 1
    n_pos, n_neg = pos.sum(), (~pos).sum()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def build_mlp(d: int, width: int):
    import torch.nn as nn

    hidden = [width, max(64, width // 4)]
    return nn.Sequential(nn.Linear(d, hidden[0]), nn.GELU(), nn.Dropout(0.1),
                         nn.Linear(hidden[0], hidden[1]), nn.GELU(), nn.Linear(hidden[1], 1))


def train(adapters, kind: str = "synthetic", model_version: str | None = None, epochs: int = 50,
          duration_s: float | None = None, batch: int = 8192, width: int = 256, lr: float = 2e-3,
          seed: int = 0) -> TrainResult:
    import torch

    from remixer.gpu.embed import model_version as clap_version

    mv = model_version or clap_version(adapters.profile["gpu"]["embedding_model"])
    ids, vecs = load_window_vectors(adapters, mv)
    if not ids:
        raise SystemExit("no window embeddings: run `remixer embed` first")
    index = {w: i for i, w in enumerate(ids)}
    ratings = [r for r in load_ratings(adapters, kind) if r["target_id"] in index]
    if kind == "synthetic" and not ratings:
        log.info("no synthetic ratings yet: planting a synthetic taste (%s)", synthesize_ratings(adapters, ids, vecs, seed=seed))
        ratings = [r for r in load_ratings(adapters, kind) if r["target_id"] in index]
    pairs = [(index[r["target_id"]], 1.0 if r["rating"] == "up" else 0.0) for r in ratings if r["target_id"] in index]
    if len(pairs) < 50:
        raise SystemExit(f"only {len(pairs)} usable {kind} ratings")
    rng = np.random.default_rng(seed)
    rng.shuffle(pairs)
    n_val = max(20, len(pairs) // 10)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    X = torch.from_numpy(vecs.astype(np.float32)).to(dev)
    idx = torch.tensor([p[0] for p in pairs], device=dev)
    y = torch.tensor([p[1] for p in pairs], device=dev)
    tr_i, tr_y, va_i, va_y = idx[n_val:], y[n_val:], idx[:n_val], y[:n_val]
    torch.manual_seed(seed)
    net = build_mlp(X.shape[1], width).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    lossf = torch.nn.BCEWithLogitsLoss()
    t0 = time.perf_counter()
    seen, ep = 0, 0
    while ep < epochs or (duration_s and time.perf_counter() - t0 < duration_s):
        perm = torch.randperm(len(tr_i), device=dev)
        net.train()
        for s in range(0, len(perm), batch):
            b = perm[s:s + batch]
            with torch.autocast(dev, dtype=torch.bfloat16, enabled=dev == "cuda"):
                loss = lossf(net(X[tr_i[b]]).squeeze(-1).float(), tr_y[b])
            if not torch.isfinite(loss):
                raise ValueError("nonfinite taste loss; refusing to save a corrupt checkpoint")
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            seen += len(b)
        ep += 1
        if duration_s and time.perf_counter() - t0 >= duration_s and ep >= 1 and ep >= epochs:
            break
    if dev == "cuda":
        torch.cuda.synchronize()
    wall = time.perf_counter() - t0
    net.eval()
    with torch.no_grad():
        sv = torch.sigmoid(net(X[va_i]).squeeze(-1)).float().cpu().numpy()
    yv = va_y.cpu().numpy()
    if not np.isfinite(sv).all() or not all(torch.isfinite(v).all() for v in net.state_dict().values()):
        raise ValueError("nonfinite taste predictions or weights; refusing to save a corrupt checkpoint")
    truth_cos = None
    truth = adapters.profile.data_dir / "state" / f"synthetic_taste_seed{seed}.npy"
    if kind == "synthetic" and truth.exists():
        with torch.no_grad():
            s_all = net(X).squeeze(-1).float().cpu().numpy()
        planted = vecs.astype(np.float32) @ np.load(truth)
        truth_cos = float(np.corrcoef(s_all, planted)[0, 1])
    out = adapters.profile.data_dir / "models" / "taste" / f"{VERSION}-{kind}-w{width}.pt"
    out.parent.mkdir(parents=True, exist_ok=True)
    set_aside_superseded(out, mv)
    torch.save({"state_dict": net.state_dict(), "width": width, "dim": X.shape[1], "kind": kind,
                "synthetic": kind == "synthetic", "embedding_model": mv, "version": VERSION}, out)
    np.savez(out.with_suffix(".npz"), **{k: v.detach().float().cpu().numpy() for k, v in net.state_dict().items()})
    res = TrainResult(kind=kind, n_train=len(tr_i), n_val=n_val, epochs=ep, samples_per_s=seen / wall,
                      val_auc=auc(sv, yv), val_acc=float(((sv > 0.5) == (yv > 0.5)).mean()),
                      truth_cos=truth_cos, path=str(out), wall_s=wall)
    adapters.events.append("stage_metrics", [{"ts": time.time(), "stage": "taste_train", "wall_s": wall,
                                              "samples_per_s": res.samples_per_s, "val_auc": res.val_auc,
                                              "synthetic": kind == "synthetic", "width": width}])
    return res
