# Model and data licenses

| Component | Use | License | Source |
|---|---|---|---|
| Demucs v4 (`htdemucs`, `htdemucs_ft`) code and weights | stem separation, heavy-mode load | MIT | github.com/facebookresearch/demucs (`demucs` 4.1.0 on PyPI; weights via huggingface.co/adefossez) |
| CLAP `laion/clap-htsat-unfused` | audio embeddings | Apache-2.0 (model card) | huggingface.co/laion/clap-htsat-unfused |
| PyTorch 2.14.1+cu130 | GPU runtime | BSD-3-Clause | pytorch.org |
| transformers 5.21 | CLAP model code | Apache-2.0 | github.com/huggingface/transformers |
| Synthetic corpus | all benchmark audio | generated in-repo (gpt-sol, T-008); no third-party audio | `src/remixer/corpus/` |

No real music was used. Generated audio and embeddings are flagged `synthetic=1` and never mix with taste data.
