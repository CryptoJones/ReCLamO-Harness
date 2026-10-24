# Provenance of the system under test

Issue #87 (epic #80). Everything the paper's numbers depend on, recorded so that the
same stack can be rebuilt. Collected on 2026-10-23 from the serving host (`pluto`), the
Hugging Face API and the harness source. No secrets and no private addresses; the host is
named, not numbered.

## 1. Model weights

| item | value |
|---|---|
| Model | Qwen3.8 Flash Next ("A Preview of the Qwen4 Architecture"), GGUF `general.architecture = qwen4exp` |
| Shape (GGUF header) | 48 blocks, embedding 2560, 512 experts, 10 used per token, context length 262,144; `general.size_label = 512x56B` |
| Quantisation | Unsloth Dynamic `UD-Q4_K_XL` (`general.file_type = 15`, quantized by Unsloth), 4 shards, 1,224 tensors, GGUF v3 |
| Variant served | the **abliterated** build: `general.abliterated_by = Huihui.ai`. Served under the name `huihui-qwen3.8-flash-next-abliterated` (aliases `qwen3.8-flash-next`, `qwen3.8-flash-next-ud-q4_k_xl`) |
| Hugging Face repo | `huihui-ai/Huihui-Qwen3.8-Flash-Next-abliterated-GGUF`, folder `UD-Q4_K_XL/` |
| Revision | the four shards were uploaded in commit `7e3bfc316b88` (2026-09-06 09:25 UTC) and are unchanged through `4fdf4dc4d851` (2026-10-09). **They were deleted from the repo on 2026-10-11** (commit `06a318de4011`, "Delete files UD-Q4_K_XL/*"), so a rebuild must pin a revision at or before `4fdf4dc4d851`. |
| Download | to the fleet NAS (telesto) and copied to `pluto:~/models/Qwen3.8-Flash-Next-GGUF/UD-Q4_K_XL/` on 2026-09-22 22:52–23:32 CDT; checksums written 2026-09-23 00:17; put into service 2026-09-23 00:20 |
| Upstream base | `Qwen/Qwen3.8-Flash-Next` (BF16 safetensors, 131 shards); the Unsloth stock quant is `unsloth/Qwen3.8-Flash-Next-GGUF` (its `UD-Q4_K_XL` shards differ from the abliterated ones by 128–160 bytes and by content) |

GGUF shard sha256 (as on disk and as the repo's LFS objects at the revisions above):

| shard | bytes | sha256 |
|---|---:|---|
| `Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf` | 10,946,752 | `290a31ca20b74ed2c21b257d378a5678d821ad9fdd8feb1fc52c719761668903` |
| `Qwen3.8-Flash-Next-UD-Q4_K_XL-00002-of-00004.gguf` | 49,859,583,296 | `0ebf70d076e0e98f74dc414a90b92c67d7267876ae524bc7799cf463e27b754b` |
| `Qwen3.8-Flash-Next-UD-Q4_K_XL-00003-of-00004.gguf` | 49,376,141,664 | `e9b12f44e13e60d6ef9396449f7b4356b2e2911222b8183a596830c2418db19a` |
| `Qwen3.8-Flash-Next-UD-Q4_K_XL-00004-of-00004.gguf` | 12,087,983,680 | `983901b3e47686f56f5fcec87ba8c51e7e2c6996277dd77bc3fc804a1d563da3` |

### Multi-token-prediction draft head (speculative decoding)

The abliterated GGUF ships no MTP head. Strata's draft head was fetched on 2026-10-05
from the **BF16 checkpoint** `Qwen/Qwen3.8-Flash-Next` at the pinned revision
`de4b8e4d43b917e7706784d8bb445c9af86a3540` (31 `mtp.*` tensors, 5,214,301,696 bytes,
read by byte range from 28 safetensors shards and sha256-checked per tensor by
`tools/mtp_fetch.py`), packed with `tools/mtp_pack.py --experts q2_0`
(`mtp/mtp-q2_0.gguf`, 889,014,272 bytes) and `tools/mtp_rt.py` into `mtp/rt/`
(`dense.bin` 116,099,072 B, `experts.bin` 707,788,800 B, `draft_vocab.bin` 425,196 B).
The Unsloth MTP GGUFs that are also on disk (`mtp-Qwen3.8-Flash-Next-Q4_K_M.gguf`,
`...-shared-Q4_K_M.gguf`, from `unsloth/Qwen3.8-Flash-Next-GGUF` at `38bb39ee9782`)
belonged to the earlier ik_llama.cpp deployment and are **not** used by Strata. The
earlier `runs/replay/stackA-provenance.json` said otherwise; this file corrects it.

Speculation does not change the sampled distribution (draft tokens are verified against
the base model), so it affects latency, not answers.

## 2. Tokenizer and chat template

| item | value |
|---|---|
| Tokenizer | GGUF `tokenizer.ggml.model = gpt2` (BPE), `tokenizer.ggml.pre = qwen35` |
| Strata tokenizer files | `packs/ud-q4_k_xl/tokenizer/`: `tokenizer.json` sha256 `c0bd435efbc6c3b28964b47999afe16c4ad268c7c7c4e8cb3af410796a6f30bf`, `vocab.json` `4ba64f0332abcfb0b600b7df1537d1e836e68009d5fb7cdb77339738dc6365c4`, `merges.txt` `4ba698529766c7a2f5052083ea10cdf2485577f5237a332ee291054eb11e3332` (extracted from shard 1 by `tools/iq_pack.py`, 2026-10-05) |
| Chat template | `tokenizer.chat_template` from the GGUF, 9,993 chars, sha256 `12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce`; the pack's `chat_template.jinja` has the same hash. Applied server-side by Strata's OpenAI-compatible front end (`serve.server`); the harness sends chat messages, never a rendered prompt |
| Harness fit checks | the harness does **not** tokenise. `reclamo.rlm.estimate_tokens` counts one token per digit and `ceil(chars / 3.5)` for everything else (`CHARS_PER_TOKEN = 3.5`, plus `MESSAGE_OVERHEAD_TOKENS = 4` per message); sub-call budgets use `SUBCALL_CHARS_PER_TOKEN = 3.0`. The plain arm's `does_not_fit` rule and `est_prompt_tokens` in every row come from this estimate |

## 3. Serving engine

| item | value |
|---|---|
| Engine | Strata, V100 fork: `https://github.com/jmnargi/Strata-V100`, commit `a4b679b1c1e283fe12cb87bb154d8fa666ce95cf` (2026-10-05 00:19:17 -0400, "Merge pull request #35 from jmnargi/fix/l3-panel-prefix-reuse") |
| Local patch | `src/core/native_dense.cpp`, 3 lines: skip `check_architecture` on continuation shards (`split.no > 0`), because the abliterated shards 2–4 carry `general.architecture` and `general.abliterated_*` keys but no `qwen4exp.*` hparams. The patch is reproduced in Appendix A below |
| ggml | from llama.cpp `3cf03257f219afbe7334045ff7c6a06ac68c627d` (vendored under `third_party/`) |
| Build | `cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON -DSTRATA_BUILD_TESTS=OFF -DCMAKE_CUDA_ARCHITECTURES="60;70;86" -DCMAKE_CUDA_COMPILER=/usr/local/cuda-12.9/bin/nvcc -DSTRATA_GGML_DIR=<third_party/llama.cpp-3cf0325…> -DSTRATA_EXPERIMENTAL_SM60=ON`; `cmake --build build --target strata`. Cache confirms `CMAKE_BUILD_TYPE=Release`, `CMAKE_CUDA_ARCHITECTURES=60;70;86`, `STRATA_ENABLE_CUDA=ON`, `STRATA_EXPERIMENTAL_SM60=ON`, `GGML_CUDA_FA=ON`, `GGML_CUDA_FA_QUANTS=q4_0-q4_0;q8_0-q8_0;f16-f16;bf16-bf16`, `GGML_CUDA_GRAPHS=OFF`, `GGML_CUDA_FORCE_MMQ=OFF`, `GGML_CUDA_FORCE_CUBLAS=OFF` |
| CUDA toolkit | nvcc `cuda_12.9.r12.9/compiler.36037853_0`; driver 580.159.04 (CUDA 13.0 runtime API) |
| Expert pack | `packs/ud-q4_k_xl/` built 2026-10-05 11:32 by `tools/iq_pack.py --gguf <shard 1> --compat-bf16` (native experts; `dense.bin` 1,485,688,320 B; `index.txt` "strata pack index v3"); expert routing profile `data/expert-profile.bin` (196,632 B, 2026-10-05) |
| Service | user unit `strata-flashnext.service`, `Environment=CUDA_DEVICE_ORDER=PCI_BUS_ID`, `ExecStart=.venv/bin/python -m serve.server --engine strata --config strata-flashnext.json --host 0.0.0.0 --port 8083` (venv Python 3.11.13). Live since 2026-10-05 13:25 CDT; restarted with the same unit and config on 2026-10-18 19:12 and 2026-10-23 11:52 CDT |
| Engine command line (as run) | `build/strata --serve --pack packs/ud-q4_k_xl --native <shard 1> --expert-profile data/expert-profile.bin --expert-cache auto --prefill auto --spec 4 --spec-min-p 0.5 --mtp mtp/rt --max-context 262144 --kv-resident 65536 --kv int8 --layer-split auto --batch 2` |
| Context / KV | max context 262,144 tokens; 65,536 tokens of KV resident on the GPUs, the rest streamed from RAM; KV cache **int8**; `parallel = 2` slots (`--batch 2`). This configuration dates from 2026-10-08 11:55 CDT (before it: `--kv-resident 32768`, f16 KV, one slot); every `runs/exp-v02` row (first row 2026-10-08 18:13 UTC) ran under it |
| Speculation | `--spec 4 --spec-min-p 0.5` suffix drafts plus the MTP head above |
| Flash attention / RoPE | ggml CUDA flash attention compiled in; attention and RoPE parameters are the GGUF's (no runtime overrides) |
| Sampling | set per request by the harness profile, not by the server: root `temperature 0.6, top_p 0.95, top_k 20, min_p 0`, thinking on, `reasoning_effort = medium`; sub-calls `temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.0`, thinking off (`reclamo/config.py`, profiles `pluto` and `pluto-long`; the GGUF's own defaults are `temp 1.0, top_p 0.95, top_k 20`) |
| Harness client | `concurrency = 2` per endpoint; the plain arm's profile `pluto-long` allows 30-minute requests; OpenAI SDK retries off, the harness's own bounded backoff on 429 / 5xx / timeouts / connection errors |

## 4. Hardware

Host `pluto`: AMD Ryzen 5 5600X (6 cores / 12 threads), 125 GiB RAM, Linux 5.14.0-687.12.1.el9_8 (RHEL 9.8 family).

| nvidia-smi index (PCI bus order) | GPU | VRAM | link | role |
|---|---|---|---|---|
| 2 | Tesla PG500-216 (V100 SXM2 32 GB on a PCIe carrier, sm70) | 32,768 MiB | PCIe Gen3 x16 (CPU lanes) | first in Strata's `gpu: [2, 0, 1]` order: holds the dense layers and most of the expert cache |
| 0 | NVIDIA GeForce RTX 3060 (sm86) | 12,288 MiB | PCIe Gen4 x4 (chipset, external PCIe dock) | second |
| 1 | Tesla P100-PCIE-16GB (sm60) | 16,384 MiB | PCIe Gen3 x4 | third |

`--layer-split auto`: at bring-up (2026-10-05, 32K resident) the split put layers 0–45 on
the V100, 46 on the 3060 and 47 on the P100, with the remaining VRAM as expert cache.
Memory in use while serving on 2026-10-23: V100 32,272 MiB, P100 10,489 MiB, 3060
8,689 MiB. The routed experts not resident on a GPU, and the model's n-gram / PLE table
(about 26.8 GiB), live in system RAM; the engine reports expert-cache hit rates of about
89% during decode. Total weights on disk: 103.7 GiB.

## 5. Where this is recorded elsewhere

- `runs/replay/stackA-provenance.json` (committed 2026-10-19): the engine commit, config
  and shard hashes, recorded for the #97 replay set. Its MTP description is superseded by
  section 1 above.
- `runs/exp-v02/commit.txt` (host only): every launch, stop and code commit of the grid.
- Each run file's `meta` records `base_url`, model, context, prompt version, limits and
  the sha256 of the active scorer set; each row records `active_source`.

## Appendix A: the local Strata patch

```diff
--- a/src/core/native_dense.cpp
+++ b/src/core/native_dense.cpp
@@ -94,7 +94,9 @@ bool NativeDense::load(const std::vector<std::string>& shards, WeightTable& tabl
             const auto* count = gguf.get("split.count");
             const auto* number = gguf.get("split.no");
             const auto* tensors = gguf.get("split.tensors.count");
-            if (gguf.get("general.architecture")) {
+            // local patch (pluto, 2026-10-05): huihui-ai abliterated shards 2-4 carry general.architecture
+            // (plus abliterated_by keys) but no qwen4exp.* hparams; treat any split.no > 0 as a continuation shard
+            if (gguf.get("general.architecture") && !(number && number->u > 0)) {
                 err = strata::check_architecture(gguf);
                 if (!err.empty()) return false;
                 have_architecture = true;
```

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
