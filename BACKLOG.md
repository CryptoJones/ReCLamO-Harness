# Backlog

Mirror of the [GitHub Issues tab](https://github.com/CryptoJones/ReCLamO-Harness/issues).
Every line here has a matching issue and vice versa; tick the box when the issue closes.

## Open

### Follow-ups from v0.1

- [ ] Real benchmark: repeated runs on OOLONG / long-context QA ([#19](https://github.com/CryptoJones/ReCLamO-Harness/issues/19))
- [ ] Independent eval on externally authored data (roundtable-authored generators in `evals/independent/`) ([#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22))

## Done

### Follow-ups from v0.1

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
