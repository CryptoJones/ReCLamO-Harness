# Backlog

Mirror of the [GitHub Issues tab](https://github.com/CryptoJones/ReCLamO-Harness/issues).
Every line here has a matching issue and vice versa; tick the box when the issue closes.

## Open

### Epic: Trained small planner — Qwen3-8B LoRA as the RLM root, Flash-Next as the reader ([#42](https://github.com/CryptoJones/ReCLamO-Harness/issues/42))

- [x] Per-role endpoints: small planner (root) + Flash-Next reader (sub-calls) ([#36](https://github.com/CryptoJones/ReCLamO-Harness/issues/36)) — PR [#44](https://github.com/CryptoJones/ReCLamO-Harness/pull/44)
- [x] Compatibility mode for mit-oasys/rlm-qwen3-8b-v0.1 as planner (upstream rlm scaffold/prompt) ([#43](https://github.com/CryptoJones/ReCLamO-Harness/issues/43)) — PR [#45](https://github.com/CryptoJones/ReCLamO-Harness/pull/45)
- [x] LongBench Pro loader: evals/longbenchpro with held-out split, MC/open tags, exam-hash exclusion ([#75](https://github.com/CryptoJones/ReCLamO-Harness/issues/75)) — PR [#78](https://github.com/CryptoJones/ReCLamO-Harness/pull/78): 1,500 items; splits grouped by shared document (practice 1,110 / dev 126 / held-out 264); MC tagged per item incl. multi-select
- [ ] Reproduce MIT's RLM-Qwen3-8B gain natively: base vs fine-tuned Qwen3-8B, 8B reader, LongBench Pro ([#74](https://github.com/CryptoJones/ReCLamO-Harness/issues/74)) — queued
- [ ] Teacher gate: Flash-Next as planner, yield of correct usable runs vs base Qwen3-8B ([#76](https://github.com/CryptoJones/ReCLamO-Harness/issues/76)) — queued
- [ ] Practice task suite (never the exam): diverse long-context generators for training data ([#37](https://github.com/CryptoJones/ReCLamO-Harness/issues/37))
- [ ] Teacher trajectories: collect and filter correct RLM runs into an SFT dataset ([#38](https://github.com/CryptoJones/ReCLamO-Harness/issues/38))
- [ ] LoRA SFT of Qwen3-8B on RunPod ([#39](https://github.com/CryptoJones/ReCLamO-Harness/issues/39)) — on hold: budget is $0 (epic decision 8), venue TBD
- [ ] Host the trained planner locally and add a profile ([#40](https://github.com/CryptoJones/ReCLamO-Harness/issues/40))
- [ ] Final exam: trained planner vs current harness vs plain model on the frozen independent tests ([#41](https://github.com/CryptoJones/ReCLamO-Harness/issues/41))

### Follow-ups from v0.1

- [ ] Real benchmark: repeated runs on OOLONG / long-context QA ([#19](https://github.com/CryptoJones/ReCLamO-Harness/issues/19))

### Harness bugs from the round-3 / #22 re-run

- [x] Fence parser misses Poolside Laguna's native `<tool_call>` syntax (turns become no_action) ([#48](https://github.com/CryptoJones/ReCLamO-Harness/issues/48)) — PR [#52](https://github.com/CryptoJones/ReCLamO-Harness/pull/52)
- [x] Compaction does not guarantee the request fits the context window (no output reserve, oversized single turn) ([#49](https://github.com/CryptoJones/ReCLamO-Harness/issues/49))
- [x] `max_errors` raises `RLMErrorLimit` with no forced finish, losing the run's work ([#50](https://github.com/CryptoJones/ReCLamO-Harness/issues/50))
- [x] `max_timeout` can be overrun: deadline checked only at turn start, out-of-turns forced finish unbounded ([#51](https://github.com/CryptoJones/ReCLamO-Harness/issues/51))
- [ ] run_eval/bench record provider errors (429 quota) as scored 0.00 rows ([#56](https://github.com/CryptoJones/ReCLamO-Harness/issues/56))
- [ ] Strata returns HTTP 400 "malformed tool call" on tool-call-shaped text in fence mode; harness loses the turn ([#72](https://github.com/CryptoJones/ReCLamO-Harness/issues/72))
- [x] Multivac scorer gives 0.2 to a correct `R142: <description> — Status: X` answer ([#63](https://github.com/CryptoJones/ReCLamO-Harness/issues/63)) — round 3.1, scorer-only; `run_eval.py --rescore`

### Evaluation

- [ ] Repeat the full main grid with qwen4exp's own sampling defaults (sampling as a factor) ([#69](https://github.com/CryptoJones/ReCLamO-Harness/issues/69))

### Fidelity to the paper (arXiv 2512.24601) and upstream rlm

- [ ] Plain baseline picks the better of two attempts using the ground truth ([#57](https://github.com/CryptoJones/ReCLamO-Harness/issues/57))
- [ ] Root prompt discourages delegation; align with the paper's main prompt ([#59](https://github.com/CryptoJones/ReCLamO-Harness/issues/59))
- [ ] v0.2 defaults: remove self-imposed limits, add `pluto-long`, pluto concurrency 2 ([#61](https://github.com/CryptoJones/ReCLamO-Harness/issues/61))

### Write-up

- [x] Draft arXiv paper: replication-and-measurement study, results pending the main grid ([#66](https://github.com/CryptoJones/ReCLamO-Harness/issues/66)) — PR [#68](https://github.com/CryptoJones/ReCLamO-Harness/pull/68): scaffold only, results PENDING

## Done

### Follow-ups from v0.1

- [x] Independent eval on externally authored data (roundtable-authored generators in `evals/independent/`) ([#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22)) — PR [#33](https://github.com/CryptoJones/ReCLamO-Harness/pull/33): frozen at `e17580f`; plain beats the harness where the context fits, and above the window the harness is exact on 5/12 answerable medium and 1/6 large cells (vs 0 for plain). Both forced-finish bugs fixed in PR [#34](https://github.com/CryptoJones/ReCLamO-Harness/pull/34); the task defects (Multivac, TheDixieFlatline, SELMA keys; MasterControl scorer) fixed in the round-2 PR. Results above were measured before the fixes; re-run after fixes in PR [#47](https://github.com/CryptoJones/ReCLamO-Harness/pull/47): rlm exact 6/16 small, 8/16 medium, 4/8 large (was 5, 5, 1) vs plain 12/16 small; gains come from the task fixes, forced-finish fixes not exercised
- [x] Optional native tool-calling protocol (`execute_python` tool) ([#20](https://github.com/CryptoJones/ReCLamO-Harness/issues/20)) — PR [#30](https://github.com/CryptoJones/ReCLamO-Harness/pull/30): `--protocol tools` added; default stays `fence` (no syntax or final-answer errors in either protocol, accuracy tied)
- [x] Live eval of depth-2 recursion (`rlm_query`) on pluto ([#18](https://github.com/CryptoJones/ReCLamO-Harness/issues/18)) — PR [#28](https://github.com/CryptoJones/ReCLamO-Harness/pull/28): default stays `max_depth=1`

### Epic: ReCLamO v0.1 — Qwen-tuned RLM harness ([#8](https://github.com/CryptoJones/ReCLamO-Harness/issues/8)) — closed 2026-10-07

- [x] Scaffold: pyproject, CI, README, NOTICE, BACKLOG, `reclamo --version` ([#1](https://github.com/CryptoJones/ReCLamO-Harness/issues/1)) — merged in PR [#9](https://github.com/CryptoJones/ReCLamO-Harness/pull/9)
- [x] Qwen-aware OpenAI-compatible client + config profiles + `reclamo ping` ([#2](https://github.com/CryptoJones/ReCLamO-Harness/issues/2)) — merged in PR [#11](https://github.com/CryptoJones/ReCLamO-Harness/pull/11)
- [x] Parsing + Qwen-tuned prompts ([#3](https://github.com/CryptoJones/ReCLamO-Harness/issues/3)) — merged in PR [#10](https://github.com/CryptoJones/ReCLamO-Harness/pull/10)
- [x] Subprocess REPL worker + stdio protocol ([#4](https://github.com/CryptoJones/ReCLamO-Harness/issues/4)) — merged in PR [#12](https://github.com/CryptoJones/ReCLamO-Harness/pull/12)
- [x] RLM loop: recursion, limits, logger, `reclamo run` (MVP) ([#5](https://github.com/CryptoJones/ReCLamO-Harness/issues/5)) — merged in PR [#13](https://github.com/CryptoJones/ReCLamO-Harness/pull/13)
- [x] Docker sandbox (`--network none`, stdio LM bridge) ([#6](https://github.com/CryptoJones/ReCLamO-Harness/issues/6)) — merged in PR [#15](https://github.com/CryptoJones/ReCLamO-Harness/pull/15)
- [x] Examples + live eval on pluto; tune prompt and defaults ([#7](https://github.com/CryptoJones/ReCLamO-Harness/issues/7)) — merged in PR [#16](https://github.com/CryptoJones/ReCLamO-Harness/pull/16)

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
