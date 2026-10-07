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
| `--max-depth N` | recursion depth; default 1 (the paper found Qwen gets worse at depth 2+; see *Depth-2 recursion* under Results) |
| `--max-iterations N` | root turns before a forced finish; default 20 |
| `--log-dir DIR` | where trajectories go; default `runs/` |
| `--verbose` | print each turn (response, code, output) to stderr |
| `--no-thinking` | disable thinking on root turns |
| `--json` | print the full result (answer, turns, sub-calls, usage, stop reason, trajectory path) as JSON |
| `--sft` | also write the SFT file (see below) |
| `--sandbox {subprocess,docker}` | where generated code runs (default `subprocess`) |

Exit codes: `0` an answer was produced (including a forced finish when turns or time
run out: whatever the REPL already holds, else one last "out of time" call), `3` a
limit stopped the run (consecutive REPL errors, token budget; any partial answer is
printed), `2` configuration or key errors, `1` the endpoint failed.

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
- `examples/nested.py` — the depth-2 task: a dict of 12 department ticket logs (~25K
  chars each, four different line formats) where each department needs format
  discovery, an open/close/reopen replay in code and a semantic read of the surviving
  complaints (the OOLONG-lite paraphrases, so grep cannot classify them). Scored by
  per-department absolute error plus whether the "most" department is right.
  `--max-depth`, `--delegate` (tell the model to use `rlm_query` per department),
  `--max-timeout`, `--dump`, `--json`.

```sh
uv run python examples/needle.py --profile pluto --lines 1000000
uv run python examples/oolong_lite.py --profile pluto --tickets 300
uv run python examples/eval.py --profile pluto
uv run python examples/nested.py --profile pluto --max-depth 2 --delegate --max-timeout 900
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

### Depth-2 recursion

[#18](https://github.com/CryptoJones/ReCLamO-Harness/issues/18). Same server and
profile, seed 0, 2026-10-07, `examples/nested.py` (12 departments, 308,990 chars).
At depth 2 the system prompt gains the `rlm_query(question, data)` tool and a
"delegate" example, and a sub-call may start a nested RLM with `data` as its own
`context`. Sub-calls include the children's own `llm_query` calls; child turns are the
root turns taken inside nested RLMs. Trajectories: `runs/20261007T094618Z-6d710f`,
`100122Z-16afdc`, `103540Z-49d014`, `104924Z-80a218`, `110425Z-3b9b20` (`.jsonl`).

| Task | Depth | Result | Turns | Sub-calls (child turns) | Tokens | Seconds |
|---|---|---|---|---|---|---|
| nested | 1 | exact: 12/12 counts, "most" right | 20 (forced finish from the answer dict) | 5 (0) | 167,301 | 275.5 |
| nested | 2, v0.1 `rlm_query(prompt)` | abs error 43, "most" right; never called `rlm_query` | 19 | 3 (0) | 180,529 | 426.0 |
| nested | 2, `rlm_query(question, data)` | abs error 73, "most" wrong; never called `rlm_query` | 16 | 4 (0) | 140,675 | 320.3 |
| nested | 2, `--delegate` | 11/12 departments exact, then `max_timeout=900` hit during the 12th; no answer returned (fixed below) | 4 (+84 child) | 16 (84) | 328,933 | 900.5 |
| oolong_lite (300 tickets) | 2 | exact: total abs error 0; never called `rlm_query` | 7 | 6 (0) | 24,910 | 137.6 |

Findings:

- **Qwen does not choose to recurse.** In three depth-2 runs it never called
  `rlm_query`, even after the tool was redesigned to take `(question, data)` and the
  prompt gained a delegate example. It did at depth 2 what it does at depth 1: dedupe
  the 477 complaints into ~110 templates, classify those with a few batched
  `llm_query` calls, and replay the open/close/reopen events in code. The two depth-2
  misses were model slips, not recursion: one 161-line batch came back with 186 labels
  (misaligned counts), and in the other run a spot-check turn decremented the result
  dict to zero and the next turn submitted it, the paper's E.2 failure, live.
- **When told to delegate, nested RLMs work but are slow.** 11 of the 11 children that
  finished were exactly right (4 to 11 turns each, 37 to 128 s, format discovery and the
  event replay in code, the semantic judgement inline in a thinking turn). At ~80 s per
  department the 12 children need ~16 min against 4.6 min for depth 1 on a server that
  takes one request at a time, and the run hit the 15 min cap on the 12th. The harness
  then threw away the eleven results: the child's timeout reached the root as a
  `RuntimeError` inside its loop and the root's own deadline check raised with no
  partial answer. Fixed in the same PR: a root timeout now gets the forced finish that
  running out of turns already had (REPL value first, else one "out of time" call).
- Depth 1 is not free either: 20 turns, mostly format discovery across 12 logs, and it
  ran out of turns with the answer already in the dict because
  `FINAL_VAR(answer['content'])` was rejected as "no such variable" (also fixed).
- **The default stays `max_depth=1`.** On pluto recursion costs about 3x the wall clock
  and 2x the tokens for the same answer, and the model will not use it unless the task
  tells it to. The per-department accuracy is the encouraging part; revisit with a
  server that runs children in parallel or a smaller per-child turn budget. One seed
  per row (pluto was shared, with 6 to 24 min lock waits per run), so these are
  observations, not a benchmark.

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
