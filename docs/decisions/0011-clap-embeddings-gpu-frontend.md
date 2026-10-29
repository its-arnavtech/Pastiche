# 0011 Embeddings: CLAP (laion/clap-htsat-unfused) with a GPU front end

- Context: the spec allows CLAP or MERT. MERT needs `trust_remote_code` (executing model-repo code); CLAP is native in transformers. The stock ClapFeatureExtractor computes log-mels in NumPy on the CPU, which would starve the GPU and steal CPU-lane cores.
- Decision: CLAP HTSAT-unfused, 512-d, fp16. Mono mix-down, 44.1 -> 48 kHz with julius, and the log-mel front end run on the GPU; numerically matched to the extractor's `rand_trunc`/`repeatpad` path (test_embed.py, max error < 0.01 dB). 5-second windows are repeat-padded to the 10-second model input exactly as the extractor does. Per-stem vector = normalized mean of its windows.
- Alternatives: MERT-v1-95M (heavier, remote code); CPU feature extraction.
- Consequences: every window costs a full 10-second HTSAT pass, which is good for GPU load and correct for the model. Vectors are checkpointed as .npy per stem; the hnswlib index is derived and rebuildable.
