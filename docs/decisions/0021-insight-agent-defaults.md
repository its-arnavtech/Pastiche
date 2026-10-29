# 0021: Insight layer defaults (thresholds, caps, budget, update rule)

- Date: 2026-10-29
- Agent: cursor-2
- Tasks: T-027

Every value is a field of `InsightConfig`, `SkepticRules`, `LifecycleConfig` or `TuningConfig`.

## When a window is worth an insight

| Rule | Default | Why |
|---|---|---|
| detector | T-014 defaults, except `min_skip_rate` comes from the per-user threshold (base 0.6) | The statistical detector is the pre-filter. No LLM call happens before it. |
| listens that reached the window | at least 3 | The same 3-listen rule as the detector. Two skips are not a pattern. |
| new insights per local day | 1, highest confidence first | About one a day, so the inbox stays quiet. |
| a "not sure" coming back | 1 per day, 7 days after the answer | Delays it without dropping it. |
| delivery | `channel="inbox"` only | There is no popup path. Constructing another channel raises. |
| re-ask after a rejection | after 3 more listens of that track | A rejected window is not sent to the model again immediately. |

## Skeptic rules (these run before the model; a hard failure never calls it)

| Confound | Default | Effect |
|---|---|---|
| intro | window starts at 0:00, or the first press is under 3 s | Hard reject. |
| few listens | reached in fewer than 3 sessions | Hard reject. |
| one session | fewer than 2 sessions did the skipping, or one session holds more than half the skips | Hard reject. |
| undo | more than 8% of skip attempts were undone | Hard reject. Under that, an overshoot is not a confound. |
| shuffle | at least 75% of skips are in shuffle, and non-shuffle listens keep it | Hard reject. Shuffle-only so far, with no other listens, is a soft downgrade. |
| time of day | at least 80% of skips in one part of the day, and other parts keep it (skip rate under 0.34, at least 2 listens) | Soft downgrade. |
| one part of the day, no contrast yet | fewer than 6 skipping sessions and no other part of the day heard it | Soft downgrade, so a listener who only listens in the evening still gets an insight once it has happened six times. |

A soft downgrade multiplies confidence by 0.5. The model's confidence is also capped by `skip_rate * min(1, skipping_sessions / 4)`, so a claim of 1.0 on three listens becomes 0.75. Ties between the rules and the model go to the stricter verdict. The model cannot overrule a rule.

## Threshold update

For a threshold `t` in `[floor, ceiling]`: a "no" (false positive) does `t + up * (ceiling - t)`; a "yes" does `t - down * (t - floor)`; "not sure" does nothing. `up` is larger than `down`.

| Key | Base | Floor | Ceiling | Up | Down |
|---|---|---|---|---|---|
| `detector.min_skip_rate` | 0.6 | 0.5 | 0.85 | 0.10 | 0.05 |
| `cause:<cause>` | 0.6 | 0.55 | 0.9 | 0.25 | 0.10 |
| `track:<track_id>` | 0.6 | 0.55 | 0.95 | 0.50 | 0.10 |

An insight surfaces only when its confidence meets both the cause threshold and the track threshold. A dismissal therefore raises the bar for that cause and that track, and also the detector rate. Every change is appended to `threshold_log`.

## Call budget (5 seeds, 24 planted dislikes and 8 of each confound, 28 days)

| | |
|---|---|
| daily budget | 30 calls |
| calls in one season | 141 (about 5 a night) |
| busiest night | 23 calls, under the budget |
| cache | a repeat of the same night makes 0 calls; replaying a season with the cache warm makes 0 calls and 149 hits |
| budget of 6 | the cap holds, 83 windows wait for the next night, recall stays 0.96 |
| rules before the model | 245 hard rejects over 5 seasons never call the model |
| a broken model | every reply invalid, every item falls back, precision and recall unchanged |

Surfaced insights over those 5 seeds: precision 0.936, recall 0.975 (117 of 120 dislikes). Intro, shuffle, few-listen and one-session confounds contributed none. Three time-of-day and five low-undo windows did surface; both are the cases the rules downgrade only once the evidence is long.
