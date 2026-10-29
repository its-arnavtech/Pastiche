# 0007 Track estimates use harmonic/percussive evidence; preserve corpus versions

Context: all 2,500 files were analyzed without errors. Blind mix estimates had
51% exact key accuracy and 5.376 BPM mean error. The harmonic `other` stem identified
all 500 keys correctly. Bass/percussion frequently mask mode in mixtures. Octave
errors clustered at tempi whose true beat lag falls halfway between onset frames.

Decision: retain independent per-file estimates and their mix-only baseline. Derive
a track summary from accompaniment harmony (`other`, then mix/vocals/bass fallback)
and percussive pulse (`drums`, then mix/bass/vocals fallback). No key/BPM truth labels
enter that function. Lower the half-lag support threshold to handle onset-frame
quantization; verify the formerly failing 138/150/154/159/164/169/175 BPM cases.
Upgrade compatible cached features without redoing unchanged LUFS/window extraction;
only unresolved low tempi can change under this rule. Re-read and hash their audio.

Measured on the original 500 tracks: track-key accuracy 100%; track BPM MAE 0.275584;
blind mix-key accuracy remains 51%, mix BPM MAE improves to 0.333788. The baseline
is preserved in data/analysis/baseline-v2.json. Refinement took 308.18 seconds on one
process and is reported separately from full-analysis throughput. These are synthetic
corpus results; they do not establish accuracy on real recordings or separated stems.
Generic chroma compression was probed with separate 300/200 seed splits but did not
resolve the harmonic ambiguity sufficiently, so it was not adopted.

The initial procedural-v1 baseline has fixed harmony/rhythm layouts with seeded
key, tempo, timbre/noise and melody variation. Extend default future generation to
procedural-v2 with eight progressions, four drum patterns, rests and velocities.
Preserve the exact v1 seed identities and bytes; expose --legacy-arrangement for
reproduction. Validate 24 v2 tracks in a separate data root after the full-budget
peak sequence so no in-flight corpus or source recipe changes underneath other agents.

Alternatives: relabel wrong estimates from manifest truth; claim mix-only key accuracy
improved; silently regenerate the existing corpus with changed synthesis. Rejected.

Consequences: downstream selection gets explicit key_source/tempo_source and can
distinguish blind and stem-supported results. Rhythm ambiguity and variation tests
remain visible in measured accuracy rather than hidden by changing ground truth.

Update after procedural-v2 integration: all 24 tracks and 120 files completed with
zero errors. Busy/syncopated drums exposed doubled and 3:2 pulse estimates. Track
tempo now uses independent mix/bass agreement to reject those percussion pulses,
and steady-bass evidence resolves a doubled transient rate. The varied set scores
0.285074 BPM MAE and 91.67% exact key accuracy; mix-only scores remain 3.800006 BPM
and 54.17% key. Original 500-track results remain 0.275584 BPM and 100% stem-supported
key after compatible bass upgrades. Truth labels are used only for evaluation.

The T-017 checkpoint arrived after lane measurements. Its arrays were entirely
nonfinite, as were three sampled CLAP embedding checkpoints. FP16 autocast had
underflowed the log-mel floor. Keep the full front end in FP32 outside autocast;
version the cache and HNSW index, reject nonfinite vectors/loss/weights, and replant
current-version ratings if only old-version synthetic history exists. Retain the
old artifacts. The coordinator must restart embedding and retrain. A corrected
CPU CLAP forward was finite. Trained export and synth-fitness adapters preserve
the exact GELU, bias, sigmoid and embedding-version contract; invalid auto-selected
weights warn and retain the explicit heuristic/random probe. Explicit trained
selection fails. Do not fabricate learned results from the corrupt checkpoint.
