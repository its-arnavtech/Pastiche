"""Recompute docs/unit-economics.md from its inputs. Run: uv run python tools/unit_economics.py

MEASURED inputs come from docs/PEAK_REPORT.md, docs/reports/cpu-lane.md and the data directory; every ASSUMPTION is
a price or a behaviour nobody measured here. Change an assumption, rerun, paste the table.
"""
from __future__ import annotations

# ---------------------------------------------------------------- measured (RTX 4060 Laptop, Core Ultra 9 185H)
DEMUCS_BEST = 66.61            # audio-s separated per second, isolated, batch 8 (PEAK_REPORT round 2)
DEMUCS_SUSTAINED = 58.40       # same, all lanes on, 15 min, final configuration
DEMUCS_HEAVY = 7.33            # htdemucs_ft + 2 shifts, 60 min (not used by the stable preset)
CLAP_WINDOWS_PER_S = 135.0     # re-embed throughput at batch 16 (PEAK_REPORT, other GPU engines)
WINDOW_S = 5.0
STEMS = 4
RENDER_ISOLATED = 12.64        # rendered audio-s per second at 8 workers, GPU idle
RENDER_HOT = 2.89              # same, final configuration with the GPU busy (shared cooling)
RENDER_WORKERS = 8
ANALYSIS_FILES_PER_MIN = 154.71  # 16 workers (cpu-lane.md), files = mix or stems
ANALYSIS_FILE_MIN = 29.94 * 60 / 500  # mean file length in minutes (500 tracks of 29.94 h, every file as long as its track)
ANALYSIS_WORKERS = 16
STEM_WAV_BYTES_PER_AUDIO_S = 4 * 44100 * 2 * 2     # 4 stems, 44.1 kHz, stereo, 16 bit = measured 42,594,252 B per stem per 241.5 s
VECTOR_BYTES = 2.2e3           # HNSW index bytes per vector: 195 MB / 88,816 vectors (data/vectors)
VECTOR_NPY_BYTES = 1024        # fp16 x 512 per window (data/embeddings)
ANALYSIS_JSON_BYTES_PER_TRACK = 196e3   # 5 files per 4.02-minute track (data/analysis)
TRACK_MIN = 241.5 / 60

# ---------------------------------------------------------------- ASSUMPTIONS (replace with quotes and measurements)
GPU_HOUR_USD = {"low (spot, small GPU)": 0.25, "base": 0.40, "high (on-demand)": 1.00}
GPU_SPEED_VS_LAPTOP = 1.0      # a cloud GPU is assumed to separate as fast as this laptop GPU does thermally limited
CPU_CORE_HOUR_USD = 0.04       # one vCPU hour on spot/preemptible capacity
STORAGE_GB_MONTH_USD = {"object storage, no egress fee": 0.015, "object storage, S3-class": 0.023}
EGRESS_GB_USD = {"zero-egress store": 0.0, "S3-class egress": 0.09}
LOSSLESS_COMPRESSION = 0.55    # FLAC of stems vs WAV (typical for music; NOT measured here)
LOSSY_STEM_KBPS = 128          # Opus/AAC per stem if the quality is acceptable (NOT tested here)
SERVER_RENDER_RECIPE_S = 32.0  # the demo's recipe length
RECIPES_PER_USER_MONTH = 100
LISTEN_H_PER_USER_MONTH = 20
EVENTS_PER_LISTEN = 6          # conservative: the demo's scripted listens averaged 3.6 (72 events / 20 listens)
LISTENS_PER_H = 15
EVENT_BYTES_PARQUET = 60       # compressed, per event (estimate)
CATALOG_TRACKS = 10_000
CATALOG_TRACK_MIN = 3.5
MAU = 1_000


def main() -> None:
    gpu_s = {"best": 3600 / DEMUCS_BEST, "sustained": 3600 / DEMUCS_SUSTAINED, "heavy": 3600 / DEMUCS_HEAVY}
    clap_s = STEMS * 3600 / WINDOW_S / CLAP_WINDOWS_PER_S
    total_best, total_sus = gpu_s["best"] + clap_s, gpu_s["sustained"] + clap_s
    print("== GPU seconds per audio hour (measured)")
    print(f"Demucs light: {gpu_s['best']:.1f} s best, {gpu_s['sustained']:.1f} s sustained; heavy would be {gpu_s['heavy']:.0f} s")
    print(f"CLAP: {STEMS} stems x {3600 / WINDOW_S:.0f} windows = {STEMS * 3600 / WINDOW_S:.0f} windows / {CLAP_WINDOWS_PER_S:.0f} per s = {clap_s:.1f} s")
    print(f"total: {total_best:.1f} s best, {total_sus:.1f} s sustained = {total_sus / 3600:.4f} GPU-hours per audio hour")
    for name, price in GPU_HOUR_USD.items():
        print(f"  at ${price:.2f}/GPU-h ({name}): ${total_sus / 3600 / GPU_SPEED_VS_LAPTOP * price:.4f} per audio hour, "
              f"${total_sus * CATALOG_TRACK_MIN / 60 / 3600 / GPU_SPEED_VS_LAPTOP * price:.5f} per {CATALOG_TRACK_MIN} min track")

    print("\n== CPU core-hours per audio hour (measured)")
    render_iso = 3600 / RENDER_ISOLATED * RENDER_WORKERS / 3600
    render_hot = 3600 / RENDER_HOT * RENDER_WORKERS / 3600
    files_h_per_min = ANALYSIS_FILES_PER_MIN * ANALYSIS_FILE_MIN / 60       # audio hours of files analysed per wall minute
    analysis_core_h = 60 / files_h_per_min * ANALYSIS_WORKERS / 3600 * STEMS  # one analysed file-hour per stem
    print(f"render: {render_iso:.3f} core-h isolated, {render_hot:.2f} core-h with a hot shared-cooling laptop")
    print(f"analysis of {STEMS} stems: {analysis_core_h:.3f} core-h per audio hour")
    print(f"  at ${CPU_CORE_HOUR_USD}/core-h: render ${render_iso * CPU_CORE_HOUR_USD:.3f}-${render_hot * CPU_CORE_HOUR_USD:.3f} per rendered hour, "
          f"analysis ${analysis_core_h * CPU_CORE_HOUR_USD:.4f} per audio hour")
    rec_core_s = SERVER_RENDER_RECIPE_S / RENDER_ISOLATED * RENDER_WORKERS
    print(f"one {SERVER_RENDER_RECIPE_S:.0f} s recipe on a server: {rec_core_s:.0f} core-s = ${rec_core_s / 3600 * CPU_CORE_HOUR_USD:.5f} "
          f"(hot: {SERVER_RENDER_RECIPE_S / RENDER_HOT * RENDER_WORKERS:.0f} core-s)")

    print("\n== Storage per audio hour")
    wav = STEM_WAV_BYTES_PER_AUDIO_S * 3600 / 1e9
    flac = wav * LOSSLESS_COMPRESSION
    lossy = STEMS * LOSSY_STEM_KBPS * 1000 / 8 * 3600 / 1e9
    vec = STEMS * (3600 / WINDOW_S + 1) * (VECTOR_BYTES + VECTOR_NPY_BYTES) / 1e6
    ana = ANALYSIS_JSON_BYTES_PER_TRACK * 60 / TRACK_MIN / 1e6
    print(f"stems: WAV16 {wav:.2f} GB (measured), FLAC ~{flac:.2f} GB (assumed {LOSSLESS_COMPRESSION:.0%}), "
          f"{LOSSY_STEM_KBPS} kbps lossy ~{lossy:.2f} GB (assumed acceptable)")
    print(f"vectors {vec:.1f} MB (index + fp16 files), analysis JSON {ana:.1f} MB")

    print(f"\n== Shared catalog of {CATALOG_TRACKS:,} tracks of {CATALOG_TRACK_MIN} min ({CATALOG_TRACKS * CATALOG_TRACK_MIN / 60:,.0f} audio hours)")
    hours = CATALOG_TRACKS * CATALOG_TRACK_MIN / 60
    for name, price in GPU_HOUR_USD.items():
        print(f"  one-off GPU ({name}): {hours * total_sus / 3600 / GPU_SPEED_VS_LAPTOP:,.1f} GPU-h = ${hours * total_sus / 3600 / GPU_SPEED_VS_LAPTOP * price:,.2f}")
    for fmt, gb in (("WAV16", wav), ("FLAC", flac), (f"{LOSSY_STEM_KBPS} kbps lossy", lossy)):
        for name, price in STORAGE_GB_MONTH_USD.items():
            print(f"  storage {fmt}: {hours * gb:,.0f} GB -> ${hours * gb * price:,.2f}/month ({name}); per MAU at {MAU:,}: ${hours * gb * price / MAU:.4f}")

    print("\n== Per active user per month")
    events = LISTEN_H_PER_USER_MONTH * LISTENS_PER_H * EVENTS_PER_LISTEN
    ev_mb = events * EVENT_BYTES_PARQUET / 1e6
    print(f"events: {events:,}/month = {ev_mb:.2f} MB Parquet -> ${ev_mb / 1000 * STORAGE_GB_MONTH_USD['object storage, S3-class']:.6f} storage")
    srv = RECIPES_PER_USER_MONTH * rec_core_s / 3600 * CPU_CORE_HOUR_USD
    print(f"server rendering of {RECIPES_PER_USER_MONTH} recipes: ${srv:.4f} (client-side rendering: $0 server CPU)")
    fetch_mb = 16 * 8 * LOSSY_STEM_KBPS * 1000 / 8 / 1e6      # 16 placements x 8 s of one stem each
    print(f"stem egress for client rendering: {fetch_mb:.1f} MB/recipe -> {fetch_mb * RECIPES_PER_USER_MONTH / 1000:.2f} GB/month; "
          + ", ".join(f"${fetch_mb * RECIPES_PER_USER_MONTH / 1000 * p:.3f} ({n})" for n, p in EGRESS_GB_USD.items()))


if __name__ == "__main__":
    main()
