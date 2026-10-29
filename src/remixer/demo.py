"""`remixer demo`: the whole product loop on about 20 synthetic tracks, in a few minutes, with light load.

ingest -> separate (Demucs, with one forced kill and resume) -> analyze -> embed (CLAP) -> taste -> plan and render
recipes -> serve them from the real FastAPI player backend -> replay a scripted listening session (single skip,
burst, undo, replay, early next) -> heatmap -> insight through the insight layer -> user ratings change the next
batch -> ban a song and re-render only the affected sections.

Runs under the stable preset (8 CPU workers, light Demucs, batch <= 8). Everything happens in its own data
directory (``<out>/work/data``), never in ``data/``. Output: ``<out>/demo.log``, ``summary.json``, ``DEMO.md``,
``audio/*.flac``, ``heatmap.png``, ``logs/*``. ``--fast`` replaces the GPU stages with ground-truth stems and
stub embeddings (for tests; the committed demo never uses it).
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from remixer.config import REPO_ROOT

SEED = 7
BPMS = (118, 120, 122, 124, 126)
KEYS = ((9, True), (0, False), (4, True), (7, False))      # A minor, C major, E minor, G major: one Camelot neighbourhood
KILL_AFTER = 4                                               # tracks separated before the forced kill
LEASE_S = 6.0                                                # short job lease so the resume does not wait 30 minutes


class Checks:
    def __init__(self, log):
        self.rows, self.log = [], log

    def __call__(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append({"check": name, "ok": bool(ok), "detail": detail})
        self.log(f"   [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
        return bool(ok)


class Demo:
    def __init__(self, out: Path, n_tracks: int = 20, duration_s: float = 30.0, fast: bool = False,
                 llm: str = "mock", kill: bool = True):
        self.out, self.n, self.dur, self.fast, self.llm_kind, self.kill = Path(out), n_tracks, duration_s, fast, llm, kill
        self.work = self.out / "work"
        self.data = self.work / "data"
        self.logs = self.out / "logs"
        self.audio = self.out / "audio"
        self.t0 = time.time()
        self.summary: dict = {"fast": fast, "tracks": n_tracks, "steps": {}}
        self.out.mkdir(parents=True, exist_ok=True)
        self._log = open(self.out / "demo.log", "w", encoding="utf-8")
        self.check = Checks(self.say)
        self.n_steps = 12

    # ------------------------------------------------------------------ plumbing
    def say(self, msg: str = "") -> None:
        line = f"[{time.time() - self.t0:6.1f}s] {msg}" if msg else ""
        print(line, flush=True)
        self._log.write(line + "\n")
        self._log.flush()

    @contextlib.contextmanager
    def step(self, i: int, title: str):
        self.say()
        self.say(f"== [{i}/{self.n_steps}] {title}")
        t = time.time()
        try:
            yield
        finally:
            self.summary["steps"][title] = round(time.time() - t, 1)
            self.say(f"   ({time.time() - t:.1f}s)")

    def env(self) -> dict:
        return {**os.environ, "REMIXER_DATA_DIR": str(self.data), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

    def cli(self, *args: str, tag: str) -> subprocess.Popen:
        self.logs.mkdir(parents=True, exist_ok=True)
        f = open(self.logs / f"{tag}.log", "ab")
        return subprocess.Popen([sys.executable, "-m", "remixer.cli", *args], env=self.env(), cwd=REPO_ROOT,
                                stdout=f, stderr=subprocess.STDOUT)

    def run_cli(self, *args: str, tag: str, timeout: float = 600) -> int:
        p = self.cli(*args, tag=tag)
        try:
            return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(p)
            raise

    @contextlib.contextmanager
    def gpu_lock(self):
        """Hold the repo's gpu lane lock while GPU stages run (AGENTS.md); the CPU cooldown comes first."""
        ctl = REPO_ROOT / "scripts" / "agentctl.py"
        if self.fast or not ctl.exists():
            yield
            return
        r = subprocess.run([sys.executable, str(ctl), "lock", "acquire", "gpu", "--owner", "wrapup", "--ttl", "15",
                            "--note", "remixer demo"], capture_output=True, text=True, cwd=REPO_ROOT)
        if r.returncode:
            raise SystemExit(f"gpu lane is locked by another agent: {r.stderr.strip() or r.stdout.strip()}")
        try:
            yield
        finally:
            subprocess.run([sys.executable, str(ctl), "lock", "release", "gpu", "--owner", "wrapup"],
                           capture_output=True, text=True, cwd=REPO_ROOT)

    def cool(self) -> None:
        from remixer.bench.stress import Limits, cooldown, read_temps
        from remixer.presets import stable_settings

        s = stable_settings()
        waited = cooldown(Limits(cooldown_c=s["cooldown_c"], cooldown_max_s=120.0))
        t = read_temps()
        self.say(f"   thermals before GPU work: CPU zone {t.get('cpu_c')} C, GPU {t.get('gpu_c')} C (waited {waited:.0f}s "
                 f"for the CPU zone to fall below {s['cooldown_c']:.0f} C)")

    # ------------------------------------------------------------------ main
    def run(self) -> int:
        shutil.rmtree(self.work, ignore_errors=True)
        for d in (self.logs, self.audio):
            shutil.rmtree(d, ignore_errors=True)
        self.data.mkdir(parents=True, exist_ok=True)
        old_env = os.environ.get("REMIXER_DATA_DIR")
        os.environ["REMIXER_DATA_DIR"] = str(self.data)
        try:
            self._run()
        finally:
            if old_env is None:
                os.environ.pop("REMIXER_DATA_DIR", None)
            else:
                os.environ["REMIXER_DATA_DIR"] = old_env
            failed = [c for c in self.check.rows if not c["ok"]]
            self.summary.update({"checks": self.check.rows, "failed": len(failed),
                                 "wall_seconds": round(time.time() - self.t0, 1)})
            (self.out / "summary.json").write_text(json.dumps(self.summary, indent=2, default=str), encoding="utf-8")
            self.say()
            self.say(f"{len(self.check.rows) - len(failed)}/{len(self.check.rows)} checks passed in "
                     f"{time.time() - self.t0:.0f}s; output in {self.out}")
            self._log.close()
        return 1 if failed else 0

    def _run(self) -> None:
        from remixer.adapters import build
        from remixer.config import load_profile
        from remixer.presets import current_mode, stable_settings

        a = build()
        self.a = a
        self.say(f"remixer demo: {self.n} synthetic tracks of {self.dur:.0f}s, mode={current_mode()}, "
                 f"{'FAST (stubs, no GPU)' if self.fast else 'real Demucs + CLAP on the GPU'}")
        self.say(f"stable preset: {stable_settings()}")
        self.say(f"data dir: {self.data} (the real data/ directory is not used)")
        self.check("stable preset active", current_mode() == "stable" and load_profile().resources.cpu_workers <= 8)

        with self.step(1, f"generate {self.n} synthetic tracks"):
            self.corpus()
        with self.step(2, "ingest into the catalog and enqueue separation"):
            self.ingest()
        with self.step(3, "separate into stems (Demucs htdemucs) with one forced kill and resume"):
            self.separate()
        with self.step(4, "analyze stems (tempo, key, LUFS) on the CPU lane"):
            self.analyze()
        with self.step(5, "embed stems and 5-second windows (CLAP)"):
            self.embed()
        with self.step(6, "train the taste model (synthetic ratings) and score every stem"):
            self.taste()
        with self.step(7, "plan 4 recipes and render them (section-cached)"):
            self.plan_and_render()
        with self.step(8, "serve them from the real player backend; replay a scripted listening session"):
            self.serve_and_listen()
        with self.step(9, "heatmap: burst, undo, replay, candidate window"):
            self.heatmap()
        with self.step(10, "insight layer: surface an insight in the passive inbox"):
            self.insight()
        with self.step(11, "ratings change the next batch (fatigue); synthetic and real stay apart"):
            self.ratings()
        with self.step(12, "ban a song: patch only the affected sections, keep every other hash"):
            self.ban()
        self.finish()

    # ------------------------------------------------------------------ 1-2 corpus, ingest
    def corpus(self) -> None:
        from remixer.corpus.generate import TrackSpec, generate_track, write_manifest

        d = self.data / "corpus"
        rows = []
        for i in range(self.n):
            tonic, minor = KEYS[i % len(KEYS)]
            rows.append(generate_track(TrackSpec(1000 + i, self.dur, 44100, bpm=BPMS[i % len(BPMS)], tonic=tonic,
                                                 minor=minor, arrangement=i % 8), d))
        write_manifest(d, rows)
        self.rows = rows
        self.say(f"   {len(rows)} tracks, {sum(r['duration'] for r in rows):.0f} audio-seconds, BPM {sorted(set(r['bpm'] for r in rows))}, "
                 f"keys {sorted(set(r['key'] for r in rows))}")
        self.check("corpus generated", len(rows) == self.n)

    def ingest(self) -> None:
        from remixer.ingest import ingest_corpus

        r = ingest_corpus(self.a, self.data / "corpus")
        self.say(f"   registered {r['registered']} tracks (all synthetic=1), enqueued {r['enqueued']} separation jobs")
        self.check("ingest registered every track", r["registered"] == self.n and r["enqueued"] == self.n)

    # ------------------------------------------------------------------ 3 separation
    def separate(self) -> None:
        if self.fast:
            return self._ground_truth_stems()
        from remixer.adapters.sqlite_queue import SqliteJobQueue

        kind = f"separate:{self.a.profile['gpu']['separation_model']}"
        q = SqliteJobQueue(self.data / "jobs.sqlite")
        with self.gpu_lock():
            self.cool()
            killed = None
            if self.kill:
                p = self.cli("separate", "--lease-s", str(LEASE_S), tag="separate-1-killed")
                t = time.time()
                while p.poll() is None and q.counts(kind).get("done", 0) < KILL_AFTER and time.time() - t < 300:
                    time.sleep(0.02)
                before = q.counts(kind)
                if p.poll() is None:
                    _kill_tree(p)
                    killed = before
                    partial = list((self.data / "stems").rglob("*.partial.wav"))
                    self.say(f"   FORCED KILL of the separation worker (pid {p.pid}) with queue {before}; "
                             f"{len(partial)} half-written stem file(s) left behind")
                else:
                    self.say(f"   worker finished before the kill ({before}); resume not exercised")
                time.sleep(LEASE_S + 1)       # in-flight leases expire; finished tracks stay done
            rc = self.run_cli("separate", "--lease-s", str(LEASE_S), tag="separate-2-resume")
            after = q.counts(kind)
            retried = q._con.execute("SELECT COUNT(*) FROM jobs WHERE kind=? AND attempts>1", (kind,)).fetchone()[0]
            partial_left = list((self.data / "stems").rglob("*.partial.wav"))
            self.say(f"   resumed worker exit {rc}; queue now {after}; jobs re-leased after the kill: {retried}; "
                     f"leftover .partial files: {len(partial_left)}")
        stems = self.a.catalog.query("SELECT COUNT(*) AS n FROM stems")[0]["n"]
        self.check("every track separated into 4 stems", stems == 4 * self.n and after.get("done") == self.n,
                   f"{stems} stems, queue {after}")
        if self.kill:
            self.check("kill-and-resume: killed mid-run, resumed, nothing lost or duplicated",
                       killed is not None and killed.get("done", 0) < self.n and after.get("done") == self.n and
                       after.get("failed", 0) == 0, f"at the kill {killed}; after resume {after}")
            self.summary["kill_resume"] = {"queue_at_kill": killed, "queue_after": after, "retried_jobs": retried}
        self.summary["separation_log"] = _tail_json(self.logs / "separate-2-resume.log")

    def _ground_truth_stems(self) -> None:
        import hashlib

        for r in self.rows:
            tid = r["hashes"]["mix"]
            for s in ("drums", "bass", "vocals", "other"):
                sid = hashlib.sha256(f"{tid}|ground-truth|{s}".encode()).hexdigest()
                self.a.catalog.upsert("stems", {
                    "stem_id": sid, "track_id": tid, "stem_name": s, "model": "ground-truth", "model_version": "gt",
                    "blob_key": Path(r["paths"][s]).relative_to(self.data).as_posix(), "duration_s": r["duration"],
                    "synthetic": 1}, key=["stem_id"])
        self.say("   FAST mode: the generator's ground-truth stems stand in for Demucs")
        self.check("stems registered", self.a.catalog.query("SELECT COUNT(*) AS n FROM stems")[0]["n"] == 4 * self.n)

    # ------------------------------------------------------------------ 4-6
    def analyze(self) -> None:
        from remixer.product import persist_analysis

        r = persist_analysis(self.a)
        n = self.a.catalog.query("SELECT COUNT(*) AS n FROM analysis")[0]["n"]
        self.say(f"   analyzed {r['analyzed']} stems with {r['workers']} workers in {r['seconds']}s")
        self.check("every stem has an analysis row", n == 4 * self.n, f"{n} rows")
        want = {(x["bpm"], x["key"]) for x in self.rows}
        got = self.a.catalog.query("SELECT a.tempo, a.key FROM analysis a JOIN stems s ON s.stem_id=a.owner_id "
                                   "WHERE s.stem_name='other'")
        keys = sum(1 for g in got if g["key"] in {k for _, k in want})
        self.say(f"   harmonic stems: key matches a true corpus key in {keys}/{len(got)}")

    def embed(self) -> None:
        if self.fast:
            return self._stub_embeddings()
        with self.gpu_lock():
            self.cool()
            rc = self.run_cli("embed", tag="embed")
        n = self.a.catalog.query("SELECT COUNT(*) AS n FROM embeddings WHERE owner_kind='stem'")[0]["n"]
        w = self.a.catalog.query("SELECT COUNT(*) AS n FROM windows")[0]["n"]
        self.say(f"   embed worker exit {rc}: {n} stem vectors, {w} window vectors")
        self.check("every stem embedded", n == 4 * self.n, f"{n} stems, {w} windows")
        self.summary["embed_log"] = _tail_json(self.logs / "embed.log")

    def _stub_embeddings(self) -> None:
        """FAST mode only: deterministic stand-in vectors (role + song + noise), registered like the real embedder."""
        import hashlib

        dim, version = 512, "stub-clap@demo-fast"
        rng = np.random.default_rng(3)
        roles = {r: rng.normal(size=dim) for r in ("drums", "bass", "vocals", "other")}
        songs: dict[str, np.ndarray] = {}
        root = self.data / "embeddings" / version.replace("@", "_")
        root.mkdir(parents=True, exist_ok=True)
        idx = self.a.vector_index(f"clap-{version.replace('@', '_')}", dim)
        for s in self.a.catalog.query("SELECT stem_id, track_id, stem_name, duration_s FROM stems ORDER BY stem_id"):
            sv = songs.setdefault(s["track_id"], rng.normal(size=dim))
            starts = list(range(0, int(s["duration_s"] * 1000), 5000))
            vecs = np.stack([roles[s["stem_name"]] + sv + 0.4 * rng.normal(size=dim) for _ in starts])
            vecs = (vecs / np.linalg.norm(vecs, axis=1, keepdims=True)).astype(np.float32)
            np.save(root / f"{s['stem_id']}.npy", vecs.astype(np.float16))
            stem_vec = vecs.mean(0)
            stem_vec /= np.linalg.norm(stem_vec)
            ids = [self.a.catalog.insert("embeddings", {"owner_id": s["stem_id"], "owner_kind": "stem", "model": "stub",
                                                        "model_version": version, "synthetic": 1})]
            rows = [stem_vec]
            for a0, v in zip(starts, vecs):
                wid = hashlib.sha256(f"{s['stem_id']}|{a0}|{version}".encode()).hexdigest()
                rid = self.a.catalog.insert("embeddings", {"owner_id": wid, "owner_kind": "window", "model": "stub",
                                                           "model_version": version, "synthetic": 1})
                self.a.catalog.upsert("windows", {"window_id": wid, "owner_id": s["stem_id"], "owner_kind": "stem",
                                                  "start_ms": a0, "end_ms": min(a0 + 5000, int(s["duration_s"] * 1000)),
                                                  "embedding_row": rid, "model_version": version}, key=["window_id"])
                ids.append(rid)
                rows.append(v)
            idx.add(ids, np.stack(rows))
        idx.save()
        self.say("   FAST mode: stub embeddings (role + song + noise) stand in for CLAP")

    def taste(self) -> None:
        from remixer.adapters.planner_catalog import latest_embedding_version
        from remixer.product import SYNTHETIC, stem_taste

        mv = latest_embedding_version(self.a.catalog)
        self.mv = mv
        if self.fast:
            from remixer.gpu.taste import train

            res = train(self.a, "synthetic", model_version=mv, epochs=30)
            auc = res.val_auc
        else:
            with self.gpu_lock():
                self.run_cli("taste", "--epochs", "30", tag="taste")
            auc = (_tail_json(self.logs / "taste.log") or {}).get("val_auc")
        self.taste_scores = stem_taste(self.a, SYNTHETIC, mv)
        vals = np.array(list(self.taste_scores.values()))
        self.say(f"   embedding version {mv}; taste scores for {len(vals)} stems, min {vals.min():.2f} mean {vals.mean():.2f} "
                 f"max {vals.max():.2f}; validation AUC {auc}")
        self.check("every stem has a finite taste score", len(vals) == 4 * self.n and np.isfinite(vals).all())

    # ------------------------------------------------------------------ 7 plan + render
    def planner_config(self):
        from dataclasses import replace

        from remixer.fatigue.selection import DEFAULT_SELECTION
        from remixer.planner.compat import CompatConfig
        from remixer.planner.plan import PlannerConfig

        # A 20-song library cannot fill 64 slots under the 5 % per-song cap (3 stems x 20 songs = 60), so the demo uses 15 %;
        # a real library of 200+ songs keeps the 5 % default. Energy tolerance is widened for the flat synthetic stems.
        return PlannerConfig(sections=4, bars_per_section=4, compat=CompatConfig(energy_tolerance=0.6),
                             selection=replace(DEFAULT_SELECTION, source_cap_fraction=0.15))

    def plan_and_render(self) -> None:
        from remixer.adapters.planner_catalog import SqliteLineage, SqliteRecipeStore
        from remixer.planner.plan import plan_and_store
        from remixer.product import SYNTHETIC, make_planner, render_and_register

        self.store, self.lineage = SqliteRecipeStore(self.a.catalog), SqliteLineage(self.a.catalog)
        self.cache = self.work / "section-cache"
        self.renders = self.work / "renders"
        planner, cat = make_planner(self.a, SYNTHETIC, self.taste_scores, time.time(), model_version=self.mv,
                                    config=self.planner_config())
        self.say(f"   planner sees {len(cat)} synthetic stems")
        self.batch0 = plan_and_store(planner, 4, SEED, self.store, self.lineage)
        self.manifests: dict[str, dict] = {}
        for r in self.batch0.recipes:
            t = time.time()
            self.manifests[r.recipe_id] = render_and_register(self.a, r, self.cache, self.renders)
            songs = sorted({p.song_id[:6] for p in r.placements})
            self.say(f"   recipe {r.recipe_id[:10]}: {len(r.sections)} sections, {len(list(r.placements))} placements, "
                     f"{r.sections[0].tempo_bpm:.0f} BPM {r.sections[0].key}, songs {songs}, rendered in {time.time() - t:.1f}s")
        from collections import Counter

        from remixer.planner.model import ROLES

        missing = Counter()
        for r in self.batch0.recipes:
            for sec in r.sections:
                missing.update(set(ROLES) - {p.role for p in sec.placements})
        quiet = Counter(s.role for s in cat.stems() if s.energy < 0.05)
        self.say(f"   unfilled slots: {self.batch0.unfilled_slots} {dict(missing)}; near-silent stems in the library: {dict(quiet)}"
                 + (" (Demucs finds almost no voice in synthetic audio, so its vocal stems are near-silent and the planner refuses "
                    "them in loud sections instead of mixing silence)" if quiet.get("vocals") and missing.get("vocals") else ""))
        self.check("4 recipes planned, every section has at least 3 of the 4 roles, and any gap has a reason",
                   len(self.batch0.recipes) == 4 and all(len(sec.placements) >= 3 and not sec.needs_regeneration
                                                         for r in self.batch0.recipes for sec in r.sections)
                   and (self.batch0.unfilled_slots == 0 or set(missing) <= {role for role, n in quiet.items() if n}),
                   f"unfilled {self.batch0.unfilled_slots}")
        # reproducible: the same recipe rendered into a fresh cache gives byte-identical audio
        r0 = self.batch0.recipes[0]
        from remixer.cpu.patch_render import render_recipe
        from remixer.product import stem_resolver

        again = render_recipe(r0, stem_resolver(self.a), self.work / "fresh-cache", self.work / "repro.wav", sample_rate=22050)
        self.check("render is reproducible (fresh cache, identical sha256)", again["sha256"] == self.manifests[r0.recipe_id]["sha256"],
                   self.manifests[r0.recipe_id]["sha256"][:16])
        self._export(r0.recipe_id, "recipe0-v1")
        for i, r in enumerate(self.batch0.recipes[1:], 1):
            self._export(r.recipe_id, f"recipe{i}-v1")

    def _export(self, recipe_id: str, name: str) -> None:
        import soundfile as sf

        wav = self.renders / f"{recipe_id[:16]}.wav"
        data, sr = sf.read(wav, dtype="int16")
        self.audio.mkdir(parents=True, exist_ok=True)
        sf.write(self.audio / f"{name}.flac", data, sr, format="FLAC", subtype="PCM_16")

    # ------------------------------------------------------------------ 8 serve + listen
    def serve_and_listen(self) -> None:
        import uvicorn

        from remixer.server.app import PlayerBackend, create_app

        self.backend = PlayerBackend(self.a)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.backend), host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        tracks = self._get("/api/tracks")
        gen = [t for t in tracks if t["source_kind"] == "generated"]
        self.say(f"   backend on {self.base}: /api/tracks lists {len(gen)} generated tracks "
                 f"({[t['duration_ms'] // 1000 for t in gen]} s)")
        t0 = gen[0]
        req = urllib.request.Request(self.base + t0["audio_url"], headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req) as r:
            head = r.read()
            self.say(f"   GET {t0['audio_url'][:30]}... Range bytes=0-1023 -> {r.status}, {len(head)} bytes, {r.headers['Content-Range']}")
            self.check("audio served with HTTP Range", r.status == 206 and head[:4] == b"RIFF")
        self.check("player lists the rendered recipes", len(gen) == 4, f"{len(gen)} generated")
        self.gen = gen
        events = self._script(gen)
        n = 0
        for i in range(0, len(events), 25):
            res = self._post("/api/events", events[i:i + 25])
            n += res["accepted"]
        self.say(f"   replayed scripted listening: {len(events)} events in {len({e['session_id'] for e in events})} sessions "
                 f"posted to /api/events -> {n} accepted")
        stored = self._get("/api/events")
        self.check("every event stored in order", n == len(events) == len(stored))
        bad = self._post("/api/events", {"event_id": "x", "session_id": "s", "track_id": "t", "track_version": "v",
                                         "event_type": "seek_fwd_10s", "position_ms": 0, "wall_time": 1,
                                         "source_kind": "source"}, expect=400)
        self.check("an invalid control (seek +10 s) is rejected", bool(bad["errors"]), bad["errors"][0][:60])

    def _script(self, gen: list[dict]) -> list[dict]:
        """Five listening sessions over ~3 days. Track 0: a single +5 s skip at ~10 s. Track 1: a burst of three +5 s
        presses 0.3 s apart. Track 2: a +5 s then a -5 s 0.9 s later (overshoot, undone). Track 3: a -5 s at 20 s
        (replay of a region just heard). In the last session track 1 gets an early next."""
        base = int(time.time() * 1000) - 3 * 86_400_000
        out: list[dict] = []

        for s in range(5):
            sess = f"demo-session-{s}"
            wall = base + s * 14 * 3_600_000 + 600_000
            for k, t in enumerate(gen[:4]):
                D = t["duration_ms"]
                st = {"pos": 0, "wall": wall}

                def e(etype: str, pos: int | None = None, jump: int | None = None) -> None:
                    """Play on to ``pos`` (wall clock follows), emit the control there, then move the playhead to ``jump``."""
                    if pos is not None:
                        st["wall"] += pos - st["pos"]
                        st["pos"] = pos
                    out.append({"event_id": f"demo-{len(out) + 1:04d}", "session_id": sess, "track_id": t["track_id"],
                                "track_version": t["track_version"], "event_type": etype, "position_ms": st["pos"],
                                "wall_time": st["wall"], "source_kind": "generated",
                                "client_info": {"seq": len(out) + 1, "synthetic": True, "agent": "remixer demo script"}})
                    if jump is not None:
                        st["pos"] = jump

                e("play", 0)
                if k == 0:
                    e("seek_fwd_5s", 10_300, 15_300)
                elif k == 1 and s == 4:
                    e("next", 6_000)
                    wall = st["wall"] + 400
                    continue
                elif k == 1:
                    e("seek_fwd_5s", 10_000, 15_000)
                    e("seek_fwd_5s", 15_300, 20_300)
                    e("seek_fwd_5s", 20_600, 25_600)
                elif k == 2:
                    e("seek_fwd_5s", 10_000, 15_000)
                    e("seek_back_5s", 15_900, 10_900)
                elif k == 3:
                    e("seek_back_5s", 20_000, 15_000)
                e("track_end", D)
                wall = st["wall"] + 400
        return out

    # ------------------------------------------------------------------ 9 heatmap
    def heatmap(self) -> None:
        from remixer.analytics.events import Event
        from remixer.analytics.heatmap import build_heatmap
        from remixer.analytics.interpret import interpret

        events = [Event.from_dict(e) for e in self._get("/api/events")]
        durations = {(t["track_id"], t["track_version"]): t["duration_ms"] for t in self.gen}
        interp = interpret(events, durations=durations)
        by_track: dict[str, list] = {}
        for l in interp.listens:
            by_track.setdefault(l.track_id, []).append(l)
        for t, name in zip(self.gen[:4], ("single skip", "burst", "undo", "replay")):
            ls = by_track.get(t["track_id"], [])
            self.say(f"   {name:11s}: {len(ls)} listens; per listen: skipped ms {[sum(b - a for a, b in l.skipped) for l in ls[:3]]}, "
                     f"presses {[sum(b.n_presses for b in l.bursts) for l in ls[:3]]}, undone ms {[sum(b - a for a, b in l.undone) for l in ls[:3]]}, "
                     f"replayed ms {[sum(b - a for a, b in l.replays) for l in ls[:3]]}, end {ls[0].end_reason if ls else '-'}")
        burst = by_track[self.gen[1]["track_id"]][0]
        self.check("a burst of 3 presses is ONE skip (one burst, three presses)",
                   len(burst.bursts) == 1 and burst.bursts[0].n_presses == 3 and 14_000 <= sum(b - a for a, b in burst.skipped) <= 16_000,
                   f"{len(burst.bursts)} burst, {burst.bursts[0].n_presses} presses, {sum(b - a for a, b in burst.skipped)} ms skipped")
        undo = by_track[self.gen[2]["track_id"]][0]
        self.check("overshoot then -5 s is an undo: the skip is cancelled", len(undo.bursts) == 1 and undo.bursts[0].cancelled and
                   not undo.skipped, f"net skipped {sum(b - a for a, b in undo.skipped)} ms, undone {sum(b - a for a, b in undo.undone)} ms")
        replay = by_track[self.gen[3]["track_id"]][0]
        self.check("a -5 s into a region just heard is a replay", bool(replay.replays), f"{sum(b - a for a, b in replay.replays)} ms replayed")
        hm = build_heatmap(events, durations=durations)
        self.hm = hm
        cands = hm.candidates()
        for c in cands[:8]:
            self.say(f"   candidate window: track {c.track_id[:8]} window {c.window_index} ({c.start_ms // 1000}-{c.end_ms // 1000}s) "
                     f"listens {c.track_listens} reached {c.reached} skipped {c.skipped} undone {c.undone} skip-rate {c.skip_rate:.2f}")
        found = {(c.track_id, c.window_index) for c in cands}
        self.check("the singly-skipped window (10-15 s) is a candidate", (self.gen[0]["track_id"], 2) in found)
        self.check("the undone skip and the replayed region are not candidates",
                   not any(c.track_id in (self.gen[2]["track_id"], self.gen[3]["track_id"]) for c in cands))
        self._plot_heatmap(hm)
        self.summary["candidates"] = [c.to_row() if hasattr(c, "to_row") else dict(c.__dict__) for c in cands]

    def _plot_heatmap(self, hm) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return
        fig, ax = plt.subplots(4, 1, figsize=(8, 6), sharex=True)
        stats = list(hm.stats())
        for axis, t, name in zip(ax, self.gen[:4], ("single skip", "burst", "undo", "replay")):
            rows = [w for w in stats if w.track_id == t["track_id"] and w.track_version == t["track_version"]]
            xs = [w.window_index * 5 for w in rows]
            axis.bar(xs, [w.skipped for w in rows], width=4.5, align="edge", color="#c0392b", label="skipped")
            axis.bar(xs, [-w.replayed for w in rows], width=4.5, align="edge", color="#27ae60", label="replayed")
            axis.bar(xs, [w.undone for w in rows], width=2.0, align="edge", color="#2980b9", label="undone")
            axis.set_ylabel(name, fontsize=8)
        ax[0].legend(fontsize=7, ncol=3)
        ax[-1].set_xlabel("seconds into the track (5 s windows)")
        fig.suptitle("Skip heatmap of the scripted sessions (5 listens per track)")
        fig.tight_layout()
        fig.savefig(self.out / "heatmap.png", dpi=110)
        plt.close(fig)

    # ------------------------------------------------------------------ 10 insight
    def insight(self) -> None:
        from remixer.adapters.insight_job import run_job
        from remixer.insights.llm import MockLLM
        from remixer.insights.mock import heuristic_script
        from remixer.insights.pipeline import InsightConfig

        if self.llm_kind == "ollama":
            llm = self.a.llm
            self.say(f"   LLM: Ollama {getattr(llm, 'model', '?')} (available: {llm.available()})")
        else:
            llm = MockLLM(heuristic_script, model="mock-heuristic")
            self.say("   LLM: deterministic MockLLM (heuristic script). Use --llm ollama for the local model.")
        now = int(time.time() * 1000)
        rep = run_job(self.a, now, llm, cfg=InsightConfig(utc_offset_minutes=0))
        self.say(f"   nightly pass: skipped={rep.get('skipped')} candidates={rep.get('candidates', rep.get('windows'))} "
                 f"calls={rep.get('llm', {}).get('calls')} errors={rep.get('errors')}")
        inbox = self._get("/api/insights")
        for row in inbox[:3]:
            self.say(f"   INBOX [{row['state']}] {row['title']}, {row['start_ms'] // 1000}-{row['end_ms'] // 1000} s: "
                     f"\"{row['hypothesis']}\" {row['why']} (answers offered: yes / no / not sure; nothing changes until the user answers)")
        self.check("an insight is waiting in the passive inbox", len(inbox) >= 1, f"{len(inbox)} item(s)")
        self.summary["insight"] = inbox[:2]
        self.summary["insight_llm"] = self.llm_kind

    # ------------------------------------------------------------------ 11 ratings
    def ratings(self) -> None:
        from remixer.analytics.events import Event
        from remixer.planner.plan import Planner
        from remixer.product import (OriginMixError, REAL, SYNTHETIC, event_origin_counts, fatigue_model, make_planner,
                                     neighbor_lookup, playback_events, stem_taste)

        r0 = self.store.head(self.batch0.recipes[0].root_id)
        placements = list(r0.placements)
        victim = next((p for p in placements if p.role == "vocals"), placements[0])   # the user rates one stem down
        tired_on = next(p for p in placements if p.stem_id != victim.stem_id and p.role != "drums")   # and is tired of another
        _, cat = make_planner(self.a, SYNTHETIC, self.taste_scores, time.time(), model_version=self.mv,
                              config=self.planner_config())
        near = [n for n, _ in cat.nearest(cat.get(victim.stem_id).embedding, 3) if n != victim.stem_id][0]
        before, _ = fatigue_model(self.a, SYNTHETIC, neighbor_lookup(cat))
        now = int(time.time() * 1000)
        t = self.gen[0]
        rating = [
            {"event_id": "demo-rate-1", "session_id": "demo-rate", "track_id": t["track_id"], "track_version": t["track_version"],
             "event_type": "rate_down", "position_ms": 3000, "wall_time": now, "source_kind": "generated",
             "client_info": {"seq": 1, "synthetic": True}, "payload": {"stem_id": victim.stem_id}},
            {"event_id": "demo-rate-2", "session_id": "demo-rate", "track_id": t["track_id"], "track_version": t["track_version"],
             "event_type": "rate_tired", "position_ms": 4000, "wall_time": now + 1000, "source_kind": "generated",
             "client_info": {"seq": 2, "synthetic": True}, "payload": {"stem_id": tired_on.stem_id}},
        ]
        self._post("/api/events", rating)
        rows = self.a.catalog.query("SELECT event_id, target_kind, rating, synthetic FROM rating_events ORDER BY event_id")
        self.say(f"   rating_events rows: {[(r['rating'], r['target_kind'], 'synthetic=' + str(r['synthetic'])) for r in rows]}")
        self.check("ratings land in rating_events tagged synthetic=1", len(rows) == 2 and all(r["synthetic"] == 1 for r in rows))
        fm, events = fatigue_model(self.a, SYNTHETIC, neighbor_lookup(cat))
        at = time.time()
        vic, nea, tir = f"stem:{victim.stem_id}", f"stem:{near}", f"stem:{tired_on.stem_id}"
        self.say(f"   fatigue before -> after: rated-down stem {before.fatigue(vic, at):.2f} -> {fm.fatigue(vic, at):.2f} "
                 f"(disliked={fm.is_disliked(vic)}); its nearest neighbour {before.fatigue(nea, at):.2f} -> {fm.fatigue(nea, at):.2f}; "
                 f"tired-of stem {before.fatigue(tir, at):.2f} -> {fm.fatigue(tir, at):.2f}")
        self.check("rating -> rating_events -> fatigue: stem disliked, neighbour and tired stems fatigued",
                   fm.is_disliked(vic) and fm.fatigue(nea, at) > before.fatigue(nea, at) and fm.fatigue(tir, at) > 0.3)
        planner, _ = make_planner(self.a, SYNTHETIC, self.taste_scores, at, model_version=self.mv,
                                  config=self.planner_config(), fatigue=fm)
        self.planner = planner
        batch1 = planner.plan_batch(4, SEED)
        old = {p.stem_id for r in self.batch0.recipes for p in r.placements}
        new = {p.stem_id for r in batch1.recipes for p in r.placements}
        self.say(f"   next batch (same seed {SEED}): {len(new)} distinct stems, {len(old & new)} shared with the first batch, "
                 f"{len(new - old)} new; rated-down stem present: {victim.stem_id in new}; tired-of stem present: {tired_on.stem_id in new}")
        self.check("the next recipe batch changed and avoids the rated-down stem", new != old and victim.stem_id not in new)
        # isolation
        counts = event_origin_counts(self.a)
        self.say(f"   playback events by origin: {counts}")
        self.check("no real-origin events or tracks exist in the demo", counts[REAL] == 0 and counts["unknown"] == 0)
        self.check("real-origin fatigue sees none of the synthetic ratings", playback_events(self.a, REAL) == [])
        try:
            stem_taste(self.a, REAL, self.mv)
            mixed = True
        except (FileNotFoundError, OriginMixError):
            mixed = False
        self.check("a real planner cannot use the synthetic taste model", not mixed)
        try:
            make_planner(self.a, REAL, {}, at, model_version=self.mv)
            mixed = True
        except ValueError:
            mixed = False
        self.check("a real-origin planner sees no synthetic stems", not mixed)

    # ------------------------------------------------------------------ 12 ban
    def ban(self) -> None:
        import collections

        import soundfile as sf

        from remixer.planner.exclusions import SongBan
        from remixer.product import patch_and_register

        heads = list(self.store.heads())
        uses = collections.Counter()
        for r in heads:
            for s in r.sections:
                for p in s.placements:
                    if p.role != "drums":
                        uses[p.song_id] += 1
        in_recipes = {song: {r.root_id for r in heads if any(p.song_id == song for p in r.placements)} for song in uses}
        song = max(uses, key=lambda s: (len(in_recipes[s]) > 1, uses[s], s))
        affected = sorted(in_recipes[song])
        before_heads = {r.root_id: r for r in heads}
        self.say(f"   banning song {song[:10]}: it is in {len(affected)} of {len(heads)} recipes")
        patches = self.planner.ban(SongBan(song), self.store, self.lineage)
        self.check("ban flagged exactly the recipes that contain the song", {self.store.get(p.old_id).root_id for p in patches} == set(affected),
                   f"{len(patches)} patches")
        ok_all = True
        total_sections = rerendered = 0
        for patch in patches:
            old_m = self.manifests[patch.old_id]
            t = time.time()
            m = patch_and_register(self.a, patch, old_m, self.cache, self.renders)
            n = len(patch.new.sections)
            total_sections += n
            rerendered += len(m["rendered_sections"])
            same = [i for i in range(n) if old_m["sections"][i]["section_hash"] == m["sections"][i]["section_hash"]]
            sr = m["sample_rate"]
            a_old, _ = sf.read(self.renders / f"{patch.old_id[:16]}.wav", dtype="int16")
            a_new, _ = sf.read(self.renders / f"{patch.new_id[:16]}.wav", dtype="int16")
            ident = all(np.array_equal(a_old[round(old_m['sections'][i]['start_seconds'] * sr):round(old_m['sections'][i]['end_seconds'] * sr)],
                                       a_new[round(m['sections'][i]['start_seconds'] * sr):round(m['sections'][i]['end_seconds'] * sr)])
                        for i in same)
            exact = (m["rendered_sections"] == list(patch.rerender) and set(m["reused_sections"]) == set(same)
                     and len(same) + len(patch.rerender) + len(patch.needs_regeneration) == n)
            ok_all &= exact and ident
            self.say(f"   recipe {patch.old_id[:8]} -> {patch.new_id[:8]}: re-rendered sections {m['rendered_sections']}, reused (cache hit, hash unchanged) "
                     f"{m['reused_sections']}, needs_regeneration {list(patch.needs_regeneration)}; unchanged-section audio byte-identical: {ident}; "
                     f"{time.time() - t:.1f}s; replacements {[(r.section, r.removed[:6], (r.added or 'none')[:6]) for r in patch.replacements]}")
            self.manifests[patch.new_id] = m
            if patch is patches[0]:
                self._export(patch.new_id, "recipe-patched-v2")
        self.check("only the affected sections were re-rendered; every other section hash and its audio is unchanged", ok_all,
                   f"{rerendered} of {total_sections} sections re-rendered across {len(patches)} recipes")
        untouched = [rid for rid in before_heads if rid not in affected]
        self.check("recipes without the song were not touched",
                   all(self.store.head(rid).recipe_id == before_heads[rid].recipe_id for rid in untouched), f"{len(untouched)} recipes")
        left = self.lineage.containing(song=song, heads_only=True)
        self.check("the banned song appears in no current recipe", not left)
        again = self.planner.plan_batch(4, SEED + 1)
        self.check("future plans avoid the banned song", all(p.song_id != song for r in again.recipes for p in r.placements))
        tracks = self._get("/api/tracks")
        gen = {t["track_id"]: t["track_version"] for t in tracks if t["source_kind"] == "generated"}
        self.check("the player now serves the patched versions", all(gen[self.store.get(p.old_id).root_id] == p.new_id for p in patches))
        noeffect = sum(len(m["unapplied_effects"]) for m in self.manifests.values())
        self.say(f"   note: {noeffect} per-stem effect entries across these renders were not applied (see docs/KNOWN_LIMITATIONS.md)")
        self.summary["ban"] = {"song": song, "recipes_affected": len(patches), "sections_rerendered": rerendered,
                               "sections_total_in_affected": total_sections}

    def finish(self) -> None:
        self.server.should_exit = True
        self.a.catalog.close() if hasattr(self.a.catalog, "close") else None
        md = [f"# remixer demo", "", f"{'FAST (stubs)' if self.fast else 'Real Demucs + CLAP on the GPU'}, {self.n} synthetic tracks, stable preset.", "",
              "| Step | Seconds |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in self.summary["steps"].items()] + ["", "## Checks", ""]
        md += [f"- {'PASS' if c['ok'] else 'FAIL'}: {c['check']}" + (f" ({c['detail']})" if c["detail"] else "") for c in self.check.rows]
        (self.out / "DEMO.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------ http
    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path) as r:
            return json.loads(r.read())

    def _post(self, path: str, body, expect: int = 200):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == expect:
                return json.loads(e.read())
            raise


def _kill_tree(p: subprocess.Popen) -> None:
    import psutil

    try:
        parent = psutil.Process(p.pid)
        for c in parent.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                c.kill()
        parent.kill()
    except psutil.Error:
        pass
    p.wait(timeout=30)


def _tail_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def cmd_demo(args) -> int:
    out = Path(args.out) if args.out else REPO_ROOT / "reports" / "demo"
    return Demo(out, args.tracks, args.duration, args.fast, args.llm, not args.no_kill).run()


def register(sub) -> None:
    p = sub.add_parser("demo", help="run the whole product loop on ~20 synthetic tracks (a few minutes, light load)")
    p.add_argument("--out", help="output directory (default reports/demo)")
    p.add_argument("--tracks", type=int, default=20)
    p.add_argument("--duration", type=float, default=30.0, help="seconds per synthetic track")
    p.add_argument("--fast", action="store_true", help="no GPU: ground-truth stems and stub embeddings (tests only)")
    p.add_argument("--llm", choices=("mock", "ollama"), default="mock")
    p.add_argument("--no-kill", action="store_true", help="skip the forced kill and resume")
    p.set_defaults(fn=cmd_demo)
