# 0008 Fatigue, credit and selection defaults

- Context: spec section 4 and the T-015 brief fix the shapes (exponential decay, loudness-weighted credit, ridge or Bayesian logistic attribution, neighbor penalty, `taste x (1 - fatigue) x novelty`, about 5 % per source) but not the numbers. All of them are configurable (`FatigueConfig`, `CreditConfig`, `SelectionConfig`, `fit_attribution(lam)`, `Attribution.culprits(min_z, min_obs)`).
- Decision:
  - Fatigue half-life 3 days. "Tired of this" adds 0.6, a thumbs-down also adds 0.3 (decaying), early next 0.10, mid next 0.05, an exposure 0.02. Increments combine as `1 - (1-f)(1-inc)`. A thumbs-up removes half the current fatigue.
  - Thumbs-down on a source or a stem, rated directly, is a permanent `disliked` flag until `rate_clear`. On a generated track it disables that track and credits -share taste evidence to its stems; it never bans a stem by itself. Culprit stems come from attribution.
  - Credit: linear power from LUFS (`10^(L/10)`) times audible time in the rated span; stems below -50 LUFS get nothing.
  - Attribution: Bayesian ridge on stem presence (or credit share), prior precision `lam = 1`. A culprit has a negative coefficient at least `min_z` posterior standard deviations below zero (default 2; the tests use 3), seen in at least 3 rated tracks.
  - Neighbor propagation: 8 nearest stems, `penalty x 0.3 x similarity`, one hop, fatigue only (never a dislike).
  - Novelty: `1 + 0.5 / (1 + exposures)`. Per-source cap `max(1, floor(0.05 x batch))`; batches come up short rather than break the cap.
  - Fatigue for a stem candidate combines the stem's and its source song's fatigue.
- Alternatives: logistic attribution via IRLS (similar ranking, needs iterations and has separation issues on small data); linear (not saturating) fatigue sums; relaxing the cap when candidates run out (silently violates the spec's 5 %).
- Consequences: a song marked "tired of this" is at 40 % weight right away, 70 % after 3 days and about 98 % after 2 weeks.
