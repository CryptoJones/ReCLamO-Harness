<p align="center"><em>Proudly Made in Nebraska. Go Big Red! 🌽 <a href="https://xkcd.com/2347/">https://xkcd.com/2347/</a></em></p>

# ReCLamO-Harness

An open-source Recursive Language Model (RLM) harness, written for the Qwen model
served by Strata on `pluto`. Apache-2.0.

## What an RLM is

A Recursive Language Model treats a long input as an *environment* rather than a
*prompt*. Instead of stuffing a million-token document into the context window, the
harness loads it into a persistent Python REPL as a variable (`context`) and asks the
model to write code that inspects, slices, searches and summarises it. The model only
ever sees the short outputs of the code it runs.

Inside that REPL the model can call the language model again (`llm_query`) on a chunk
of the data, or start a nested RLM (`rlm_query`) that gets its own REPL. Results stay in
variables; only small summaries flow back up. The run ends when the model marks an
answer as final. This is the scheme described in *Recursive Language Models*
(Zhang, Kraska and Khattab, [arXiv 2512.24601](https://arxiv.org/abs/2512.24601)),
which shows a frontier model handling inputs far beyond its native context window and
degrading gracefully as inputs grow.

ReCLamO-Harness is a clean-room implementation of that loop, sized like
`rlm-minimal` and borrowing the useful parts of the full `rlm` package (depth
recursion, batched sub-calls, limits, JSONL trajectories). What is new here is the
Qwen tuning: `<think>` handling, the paper's "do not over-call" guidance, hard caps on
sub-calls, and a prompt sized for the 32K of KV cache that stays resident on pluto.

## Status

**Pre-alpha.** Work is tracked in epic
[#8](https://github.com/CryptoJones/ReCLamO-Harness/issues/8) and mirrored in
[BACKLOG.md](BACKLOG.md). Right now the package installs and `reclamo --version`
works; nothing else does yet.

## Quickstart (coming)

The target interface, against the `pluto` profile. Not yet implemented.

```sh
uv sync
uv run reclamo ping --profile pluto
uv run reclamo run --profile pluto --context ./big.txt --query "Which line holds the needle?"
```

The `pluto` profile points at `http://pluto:8083/v1`, model `qwen3.8-flash-next`,
reads the API key from `RECLAMO_API_KEY` or `pass pluto/flashnext-api-key`, and
serialises calls (Strata serves one request at a time). Generated code runs in a
subprocess REPL by default; `--sandbox docker` runs it in a container with
`--network none`.

## Development

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest            # live tests (-m live) are skipped by default
```

## Credits

- Alex L. Zhang, Tim Kraska and Omar Khattab, *Recursive Language Models*,
  [arXiv 2512.24601](https://arxiv.org/abs/2512.24601).
- [alexzhang13/rlm](https://github.com/alexzhang13/rlm) and
  [alexzhang13/rlm-minimal](https://github.com/alexzhang13/rlm-minimal), both MIT.
  This project follows their design; see [NOTICE](NOTICE) and
  [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
