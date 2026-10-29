# 0014: Recipe planner defaults (thresholds, sampling, replacement ranking)

- Date: 2026-10-29
- Agent: cursor-opus
- Tasks: T-021

Every value below is a field of `PlannerConfig`, `CompatConfig` or `SelectionConfig`, so any of them can
be changed without code changes.

## Recipe shape

| Setting | Default | Why |
|---|---|---|
| sections | 4 x 8 bars | About 1 minute at 120 BPM; small enough that one ban re-renders a fraction of a track. |
| energy curve | 0.45, 0.7, 0.9, 0.6 | Intro, build, peak, outro. |
| roles | drums, bass, vocals, other | One per role per section (the brief's role constraint). |
| target loudness | -14 LUFS, gain clipped to +/-12 dB | Streaming-level loudness. Clipping avoids boosting noise. |
| effects | vocals reverb_mix 0.15, other highpass 120 Hz | Minimal, deterministic defaults the renderer can ignore. |

The tempo, key and meter of a recipe come from an anchor stem (any non-drum stem), drawn like every other choice.

## Compatibility (`CompatConfig`)

| Rule | Default | Why |
|---|---|---|
| tempo stretch | within 8 percent | Beyond about 8 percent, time-stretch artifacts become audible on vocals. |
| half/double time | allowed, fit x 0.9 | Hip-hop at 87 and drum and bass at 174 mix well; native tempo is preferred. |
| key | Camelot distance <= 1 after a pitch shift of at most 2 semitones | Same key, adjacent key or relative major/minor are the standard harmonic-mixing moves. Shifts above 2 semitones sound processed. |
| key cost | 0.15 per Camelot step + 0.1 per semitone | Fit = 1 - cost. With equal cost, the smaller shift wins, then the upward shift. |
| drums | key-agnostic | Unpitched. |
| beat grid | same meter; source ranges start on a source downbeat | Bars line up after stretching. |
| energy | within 0.35 of the section target; fit 1 - 0.5 x diff / 0.35 | Keeps builds and drops recognizable without starving candidates. |

## Scoring and sampling

- Weight = `fatigue.selection.candidate_weight` (taste x (1 - fatigue) x novelty; 0 for disliked stems or songs) x compatibility fit x diversity.
- Diversity = `1 / (1 + 1.0 x uses_in_this_batch + 0.25 x uses_in_earlier_batches)` per song. The batch term spreads use within a batch; the ledger term spreads it across batches, so library coverage keeps growing.
- Per-song cap: `fatigue.selection.source_cap(slots)`, which is `max(1, floor(0.05 x stem slots in the batch))`. Slots are counted, not filled stems, so the cap is known before planning starts.
- Sampling is Gumbel top-k: `argmax(log w + G)`, with `G` from `splitmix64(hash(seed, batch, recipe, section, role) ^ hash(stem_id))`.
  - Plain argmax would always pick the same favorites. Numpy RNG streams would make a choice depend on candidate order and on how many draws came before.
  - Hashed noise gives exact `w / sum(w)` sampling. It is byte-reproducible and independent of catalog order and of which other stems exist.
  - The best 64 candidates are examined per slot, with up to 16 downbeat positions each, starting at a hashed offset.
- Confirmed insights block source ranges that overlap them (through `blocked_by_insight`). Unconfirmed insights are not consulted.

## Replacement ranking (ban-and-replace)

- Candidates are restricted to the same role, compatible with the section target under the same rules, not banned, with non-zero weight, under the batch cap (counted over the batch's current heads), and with a source range that avoids other sections' windows and confirmed insights.
- Score = `((1 + cos(candidate, removed)) / 2)^4 x fit x selection weight`.
  - The power of 4 makes sound similarity dominate, so a replacement is "the nearest stem", as the spec asks. Fit and taste still separate near-ties.
- Ties are broken by `stem_id`. There is no noise, so the replacement is fully determined: the best compatible candidate, which the brute-force tests check.
- The source start is the valid downbeat position nearest the removed stem's start.
- If nothing qualifies, the section is marked `needs_regeneration`, with the banned stem removed. A bad match is never forced.

## Exclusions

- Rest stays a fatigue signal (`FatigueModel.tired`) and is rejected as a ban.
- Song, stem-type and sound bans resolve to stem sets. Sound bans use the cosine-distance ball, with radius chosen per ban.
- Patches handle affected recipes in `recipe_id` order, so patching is reproducible.
