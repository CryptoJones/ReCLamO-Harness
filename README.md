<p align="center"><em>Proudly Made in Nebraska. Go Big Red! 🌽 <a href="https://xkcd.com/2347/">https://xkcd.com/2347/</a></em></p>

# ReCLamO-Harness

> 📝 **Background reading:** [*Mismanaged Geniuses*](https://cryptojones.dev/Mismanaged-Geniuses/) — why recursive language models matter, from Alex Zhang's interview on RLMs.

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

**Pre-alpha, usable.** Work is tracked in epic
[#8](https://github.com/CryptoJones/ReCLamO-Harness/issues/8) and mirrored in
[BACKLOG.md](BACKLOG.md). `reclamo ping` and `reclamo run` work end to end against
pluto; the Docker sandbox and the live eval are the remaining children.

## Quickstart

```sh
uv sync
uv run reclamo ping --profile pluto
uv run reclamo run --profile pluto --context ./big.txt -q "Which line holds the needle?"
```

`ping` lists the server's models, sends one short non-thinking request and one
thinking request, and reports latency, token usage and whether reasoning came back.

`run` loads the context into a REPL and drives the model until it answers:

| Flag | Meaning |
|---|---|
| `--context PATH\|-` | a text file; a directory (loaded as `{relative path: text}`, hidden and non-UTF-8 files skipped); or `-` for stdin |
| `-q, --query` | the question |
| `--max-depth N` | recursion depth; default 1 (the paper found Qwen gets worse at depth 2+) |
| `--max-iterations N` | root turns before a forced finish; default 20 |
| `--log-dir DIR` | where trajectories go; default `runs/` |
| `--verbose` | print each turn (response, code, output) to stderr |
| `--no-thinking` | disable thinking on root turns |
| `--json` | print the full result (answer, turns, sub-calls, usage, stop reason, trajectory path) as JSON |
| `--sft` | also write the SFT file (see below) |
| `--sandbox {subprocess,docker}` | where generated code runs (default `subprocess`) |

Exit codes: `0` an answer was produced (including a forced finish when turns run out),
`3` a limit stopped the run (timeout, consecutive REPL errors, token budget; any
partial answer is printed), `2` configuration or key errors, `1` the endpoint failed.

### Profiles

Two profiles are built in. `pluto` points at `http://pluto:8083/v1`, model
`qwen3.8-flash-next`, with Qwen's recommended sampling for thinking (root) and
non-thinking (sub-call) turns, `concurrency = 1` (Strata serves one request at a
time) and `context_tokens = 32768` (the KV cache that stays resident).
`openai-compatible` is a generic profile for any OpenAI-style server.

Add or override profiles in `~/.config/reclamo/profiles.toml` (or the file named by
`RECLAMO_PROFILES`). Fields you leave out keep the built-in values:

```toml
[profiles.pluto]
max_iterations = 30          # override one field of a built-in profile

[profiles.lab]               # a new profile
base_url = "http://lab:8000/v1"
concurrency = 2
context_tokens = 65536
subcall_chars = 16000        # how much text the prompt tells the model to batch per sub-call
max_subcalls_per_run = 64
max_subcalls_per_exec = 24
exec_timeout = 120.0         # seconds per REPL execution
max_timeout = 1800.0         # seconds for the whole run

[profiles.lab.root]          # the loop's own turns
model = "qwen3-32b"
max_tokens = 4096
enable_thinking = true
reasoning_effort = "medium"
sampling = { temperature = 0.6, top_p = 0.95, top_k = 20, min_p = 0.0 }

[profiles.lab.sub]           # llm_query calls
model = "qwen3-32b"
max_tokens = 2048
enable_thinking = false
sampling = { temperature = 0.7, top_p = 0.8, top_k = 20, presence_penalty = 1.0 }
```

Environment overrides apply to any profile: `RECLAMO_BASE_URL`, `RECLAMO_MODEL`
(sets both roles) and `RECLAMO_API_KEY`. When `RECLAMO_API_KEY` is unset the key
comes from the profile's `api_key_cmd` (`pass pluto/flashnext-api-key` for pluto).
Non-standard sampling keys such as `top_k` and `min_p` are sent in the request body,
and `enable_thinking` goes out as `chat_template_kwargs`, which Strata and vLLM-style
servers honour.

### Trajectories and the SFT log

Every run writes `runs/<UTC timestamp>-<id>.jsonl`, one JSON object per line:

- `metadata` — profile (never the key), query, context shape, depth
- `iteration` — turn number, the model's content, its reasoning as a separate field,
  the code blocks, each block's result, any nudges, and the FINAL decision
- `subcall` — depth, kind (`llm_query`, `llm_query_batched`, `rlm_query`), prompt and
  answer sizes, latency, running count
- `compaction` — when older REPL outputs were elided from the history
- `forced_finish` and `final` — how the run ended

Reasoning is logged but never fed back into the history, per Qwen's guidance. With
`--sft` a second file, `<same stem>.sft.jsonl`, holds one line per root turn,
`{"messages": <history before the turn>, "completion": <content>}`, the format the
paper used to fine-tune RLM-Qwen3-8B.

## Security model

The model writes code, and that code runs. Two things keep that contained.

**Subprocess REPL (default).** Generated code runs in a separate `python -I` process
whose environment is scrubbed to `PATH`, `LANG`, `LC_ALL` and a throwaway `HOME` and
`TMPDIR`. No `RECLAMO_*`, `OPENAI_*` or `*_API_KEY` variable reaches it. The worker's
protocol stdio is duplicated to private descriptors before user code runs, and fd 0
is pointed at `/dev/null` and fd 1 at stderr, so generated code (or anything it
spawns) can neither read protocol messages nor corrupt the stream. Each execution
has a wall-clock timeout; a hung or crashed worker is killed and relaunched, and the
model is told its variables are gone. Sub-calls per execution and per run are capped
in code, not just in the prompt.

**Docker sandbox** (`--sandbox docker`, [#6](https://github.com/CryptoJones/ReCLamO-Harness/issues/6)).
The same worker runs in `python:3.12-slim` with `--network none`, a read-only root
filesystem, a small `/tmp`, no capabilities and a non-root user. The only channel out
is the JSON-lines protocol on stdio, which is how `llm_query` still works with no
network.

**What the key can reach.** The API key lives only in the parent process and is used
for one thing: requests to the configured LM endpoint. It is never passed to the
REPL, never written to a trajectory, and never included in an error message.

## Examples and eval

- `examples/needle.py` — builds N synthetic lines (default 1,000,000, about 30 MB) with
  one passphrase line and asks for the passphrase. Exit 0 when found.
- `examples/oolong_lite.py` — about 300 synthetic support tickets in five categories,
  written as paraphrases that never contain their category's words (asserted at
  generation time), so grep cannot solve it and the model has to read, which means
  batching tickets into `llm_query` calls. Scored by per-category absolute error.
  `--dump` prints the tickets and the ground truth without calling a model.
- `examples/eval.py` — runs both against a profile, writes `runs/eval-<timestamp>.json`
  and prints the markdown table used below.

```sh
uv run python examples/needle.py --profile pluto --lines 1000000
uv run python examples/oolong_lite.py --profile pluto --tickets 300
uv run python examples/eval.py --profile pluto
```

Live tests (`uv run pytest -m live`) run `ping`, a thinking round trip and a
50K-line needle against pluto; they are skipped by default and in CI.

## Results

`examples/eval.py --profile pluto`, seed 0, run 2026-10-07 against
`huihui-qwen3.8-flash-next-abliterated` (Qwen3.8-Flash-Next, UD-Q4_K_XL) served by
Strata on pluto (V100 32 GB + P100 16 GB + RTX 3060 12 GB, one request at a time,
32K resident KV). Default `pluto` profile: root thinking on, sub-calls thinking off,
`subcall_chars=12000`, depth 1.

| Task | Result | Turns | Sub-calls | Tokens | Seconds |
|---|---|---|---|---|---|
| needle (1,000,000 lines, ~30 MB) | found | 4 | 0 | 7,022 | 18.6 |
| oolong_lite (300 tickets, 5 categories) | exact: total abs error 0 | 6 | 3 | 21,279 | 127.7 |

Notes:

- The needle is solvable with code alone; Qwen scans for the odd line and never needs a
  sub-call. The context is ~1,000x the model's resident window.
- OOLONG-lite cannot be grepped. Qwen batched the tickets into **3** `llm_query` calls
  of ~100 tickets each and aggregated in the REPL, instead of one call per ticket. That
  is the over-calling failure the RLM paper reports for Qwen3-Coder (hundreds of calls
  per task), held off here by the batching instruction plus hard caps in code.
- One run per task; treat these as smoke results, not a benchmark.

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
