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
| `--protocol {fence,tools}` | how the root model acts: fenced code + `FINAL` text (default), or `execute_python` / `final_answer` tool calls (see *Protocol* under Results) |

Exit codes: `0` an answer was produced (including a forced finish when turns or time
run out: one last call that shows the model what the REPL holds and asks for `FINAL` /
`FINAL_VAR`, falling back to the answer dict, then an answer variable, then the reply's
prose with code removed), `3` a
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
- `forced_finish` and `final` — how the run ended. `forced_finish.source` says where a
  forced answer came from: `model` (a valid `FINAL` / `FINAL_VAR` / `final_answer` in
  the forced reply), `answer_dict`, `variable` (with its name), `reply_text` (the
  reply's prose, code and thinking removed) or `empty`

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

- `examples/longdoc_qa.py` — two-hop questions over a long synthetic engineering digest:
  each project's owner and that person's office city sit in different sections among
  distractors, so answering needs two hops of reading. Exact-match on the city.
- `examples/bench.py` — the repeatable benchmark: harness vs plain model, N seeds over a
  task × size grid, resumable (`--resume`), with a markdown summary (`--summary-only`).
- `evals/independent/run_eval.py` — the frozen independent eval (#22): the same rlm and
  plain modes on the eight roundtable-authored tasks, scored by each task's own
  `score()`; resumable, with a markdown summary.

```sh
uv run python examples/needle.py --profile pluto --lines 1000000
uv run python examples/oolong_lite.py --profile pluto --tickets 300
uv run python examples/eval.py --profile pluto
uv run python examples/bench.py --profile pluto --seeds 3
uv run python examples/nested.py --profile pluto --max-depth 2 --delegate --max-timeout 900
```

Live tests (`uv run pytest -m live`) run `ping`, a thinking round trip and a
50K-line needle against pluto; they are skipped by default and in CI.

## Results

There are two kinds of result here. The **independent evaluation** comes first: it uses
tasks written by eight non-Anthropic models that had no part in building the harness.
The smoke, benchmark, protocol and depth-2 results after it use tasks written by the
same Claude models that wrote the harness and its prompt, so they likely overstate
what the harness can do.

### Independent evaluation (tasks written by other models)

[#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22). The tasks are the eight
generators in [`evals/independent/fixed/active/`](evals/independent/), written by the
non-Anthropic lanes of the Flatline Roundtable. Each answer is scored by that
generator's own `score()`, where 1.0 means exact. We did not write or change any
question, answer key or scorer.

**Frozen harness: commit `e17580fb76b06ece39ba381ce26763aa870bca90`.** Nothing was
tuned on these tasks. The run used the default `pluto` profile, the fence protocol,
depth 1 and default caps (20 turns, 64 sub-calls), plus `max_timeout=900` s per run.
It took 3.5 hours on 2026-10-07, one row at a time under the pluto lock. Every
batch's metadata records that `src/`, `examples/` and `pyproject.toml` were unchanged
from the frozen commit.

The model was the same as in the sections below: `huihui-qwen3.8-flash-next-abliterated`
served by Strata on pluto. The runner is
[`evals/independent/run_eval.py`](evals/independent/run_eval.py), which imports
`bench.py`'s two modes:

- **rlm** is the harness.
- **plain** is one call with the whole context in the prompt, the better of thinking on
  (16K output cap) and thinking off. It is recorded as "does not fit" when the prompt
  is larger than pluto's 28,672 usable tokens.

The grid was 8 tasks × small (~60K chars), medium (~300K) and large (~1.2M), with seed
0 for every cell and seed 1 for small and medium: 80 rows and no errors. Raw rows are in
`runs/independent-20261007.json`, with one trajectory per rlm row in `runs/` (not in
git).

Each cell shows seed 0 / seed 1. **†** marks a cell whose answer key cannot be reached
from the context (see "Defects in the tasks" below).

| Task (author model) | Size | rlm score | plain | rlm turns | rlm sub-calls | rlm s | rlm stop |
|---|---|---|---|---|---|---|---|
| GLaDOS (grok-4.6) | small | 1 / 0.60 | 1 / 1 | 20 / 20 | 0 / 0 | 318 / 488 | out of turns / answer_dict |
|  | medium | 0.20 / 0.60 | does not fit (~148K tokens) | 20 / 20 | 0 / 0 | 296 / 247 | out of turns / out of turns |
|  | large | 0.20 | does not fit (~606K tokens) | 20 | 0 | 193 | out of turns |
| SHODAN (gpt-6-astra) | small | 0 / 0 | 1 / 0 | 20 / 20 | 10 / 0 | 475 / 178 | out of turns / out of turns |
|  | medium | 0 / 0 | does not fit (~88K tokens) | 20 / 20 | 2 / 0 | 275 / 134 | out of turns / out of turns |
|  | large | 0 | does not fit (~353K tokens) | 20 | 0 | 168 | out of turns |
| TheDixieFlatline (gemini-3.1-pro-high) | small | 0† / 0† | 0† / 0† | 12 / 11 | 0 / 0 | 108 / 231 | final / answer_dict |
|  | medium | 0† / 0 | does not fit (~96K tokens) | 14 / 17 | 0 / 0 | 99 / 181 | answer_dict / final |
|  | large | 0 | does not fit (~396K tokens) | 20 | 0 | 180 | out of turns |
| Cerebex (glm-5.3-flash) | small | 0 / 0 | 0.50 / 1 | 20 / 20 | 6 / 0 | 379 / 353 | out of turns / out of turns |
|  | medium | 0 / 1 | does not fit (~93K tokens) | 20 / 20 | 0 / 0 | 300 / 460 | final / out of turns |
|  | large | 0 | does not fit (~373K tokens) | 20 | 0 | 242 | out of turns |
| Neuromancer (deepseek-v4-flash) | small | 1 / 1 | 1 / 1 | 10 / 16 | 0 / 0 | 77 / 315 | final / answer_dict |
|  | medium | 0 / 1 | does not fit (~86K tokens) | 17 / 20 | 0 / 1 | 210 / 445 | final / final |
|  | large | 0 | does not fit (~350K tokens) | 20 | 3 | 808 | out of turns |
| SELMA (nemotron-3-super-120b-a12b) | small | 1 / 0† | 1 / 0† | 7 / 5 | 0 / 0 | 71 / 58 | answer_dict / final |
|  | medium | 1 / 0† | does not fit (~89K tokens) | 8 / 7 | 0 / 0 | 75 / 70 | final / answer_dict |
|  | large | 0† | does not fit (~358K tokens) | 9 | 0 | 136 | final |
| MasterControl (mistral-medium-3.1) | small | 0.50 / 1 | 1 / 1 | 11 / 12 | 0 / 0 | 209 / 106 | answer_dict / answer_dict |
|  | medium | 1 / 1 | does not fit (~86K tokens) | 14 / 9 | 0 / 0 | 211 / 113 | answer_dict / answer_dict |
|  | large | 1 | does not fit (~343K tokens) | 9 | 0 | 124 | final |
| Multivac (hermes-4-405b) | small | 0† / 0† | 0† / 0† | 7 / 4 | 0 / 0 | 54 / 23 | final / answer_dict |
|  | medium | 0† / 0† | does not fit (~104K tokens) | 5 / 5 | 0 / 0 | 67 / 43 | answer_dict / answer_dict |
|  | large | 0† | does not fit (~428K tokens) | 5 | 0 | 29 | answer_dict |

What each task asks (from `manifest.json`):

- **GLaDOS**: the net authorized amount and certifying member of a renamed project's
  legal successor, under bylaws and an SOP.
- **SHODAN**: the earned credit per office after signed corrections, custody findings
  and agreement terms.
- **TheDixieFlatline**: the final room of an asset through renames and transfers.
- **Cerebex**: the travel total after amendments and reversals.
- **Neuromancer**: March travel reimbursed after adjustments and denials.
- **SELMA**: the final owner of a review after reassignments.
- **MasterControl**: the one employee flagged for two issues, and their total.
- **Multivac**: the status and description of a requirement after merges and splits.

Accuracy by size. A cell is one task × size × seed. A plain prompt that does not fit
scores 0.

| Size | Cells | rlm mean | rlm exact | plain mean | plain exact | plain does not fit | Answerable cells | rlm mean | rlm exact | plain mean | plain exact |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small (~60K) | 16 | 0.38 | 5/16 | 0.59 | 9/16 | 0/16 | 11 | 0.55 | 5/11 | 0.86 | 9/11 |
| medium (~300K) | 16 | 0.36 | 5/16 | 0.00 | 0/16 | 16/16 | 12 | 0.48 | 5/12 | 0.00 | 0/12 |
| large (~1.2M) | 8 | 0.15 | 1/8 | 0.00 | 0/8 | 8/8 | 6 | 0.20 | 1/6 | 0.00 | 0/6 |

Findings:

- **Where the context fits, the plain model is clearly better.** At ~60K characters,
  plain was exact on 9 of the 11 answerable cells; the harness managed 5. Plain also
  took a median 17 s for the chosen call, or 154 s for both variants, against 194 s
  for the harness. On SHODAN, Cerebex and GLaDOS small, plain was exact where the
  harness ran out of turns or finished with the wrong total. The self-authored benchmark
  below showed a tie at this size. These tasks show a loss.
- **Where it doesn't fit, the harness is the only option, and it is weak.** From ~300K
  characters up, plain cannot attempt any cell. The harness was exact on 5 of 12
  answerable medium cells and 1 of 6 large ones, with a mean of 0.48 and then 0.20. It
  was reliable on one task, MasterControl (exact at medium and large on both seeds),
  and good on SELMA whenever the key was answerable. It won occasionally on Neuromancer,
  Cerebex and GLaDOS (partial credit). It never solved SHODAN at any size, nor
  TheDixieFlatline when that task was answerable. In the self-authored benchmark, by
  contrast, the harness was exact on every row where plain did not fit except one
  1,000-ticket seed, up to ~16M tokens.
- **The main failure is running out of turns.** 15 of the 40 rlm rows hit the 20-turn
  limit, and only 2 of those 15 were then exact. The trajectories show the same pattern
  on the reconciliation tasks (SHODAN, Cerebex, GLaDOS): many turns printing sections
  to read them, then a hand-written regex parser per section, then the limit.
  One example is `runs/20261007T204104Z-a03836.jsonl`, SHODAN small, where the forced
  finish says it is "out of turns but must answer" and guesses.
- **Qwen almost never delegates to sub-calls.** Only 5 of the 40 rlm rows made any
  `llm_query` call. Each generator says it was built so that grep fails, yet the model
  greps and slices the context in code and then reads the slices itself. In the
  self-authored benchmark OOLONG-lite drew batched sub-calls. These tasks did not.
- **Clean protocol.** 560 code executions produced 1 syntax error and 3 execution errors,
  with 0 rejected finals, 3 turns with neither code nor a final, and no row errors or stalls.
  The losses are in reasoning and the turn budget, not in the loop.
- **Comparison with the earlier medium seed-0 run.** The protocol section below scored
  the fence protocol at a mean of 0.28 with 2/8 exact on the same medium seed-0 cells.
  This run got 0.28 and 2/8 exact again, on the same two tasks. That run looked only at
  protocol and changed nothing; the harness is unchanged since.

Harness bugs found. Both were **fixed after this run**, in the forced-finish PR that
followed it ([#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22)). The
numbers above are still the ones measured on frozen `e17580f`, and no row was re-run:

1. **The forced finish can return a stale REPL variable instead of the answer.** When a
   run runs out of turns, `_forced_finish` returns the first variable it finds named
   `final_answer`, `answer_text`, `result` or `final`. It does this before asking the
   model, and it does not check how recent the value is. In Neuromancer large
   (`runs/20261007T220642Z-c69a18.jsonl`), turn 20 printed `Final answer: $91049.09`,
   which is exactly right. The run instead returned `result`, set on turn 18 to an
   `llm_query` reply (a prose chain analysis), and scored 0. `result` is a common name
   for a sub-call's reply, so this can recur. **Fixed:** the forced finish now always
   makes one more call. That call's prompt shows the current value of `answer['content']`
   and of each of those variables (300 characters each) plus the end of the last REPL
   output, and asks for `FINAL(...)` or `FINAL_VAR(name)`. A valid reply wins. The
   variables are only a fallback, after the answer dict, so a good value already in the
   REPL is still kept (paper E.2) but no longer beats an answer the model just printed.
2. **The forced finish can return code as the answer.** When the model's forced-finish
   reply has no `FINAL(...)`, the whole reply becomes the answer. Twice that reply was a
   ```` ```repl ```` block, and the code was scored as the answer: SHODAN large seed 0
   (`runs/20261007T215541Z-947e9c.jsonl`) and SHODAN small seed 1
   (`runs/20261007T223915Z-dd5502.jsonl`). **Fixed:** when the forced reply has no
   usable final, the fallbacks are the answer dict, then an answer variable, then the
   reply's prose with every code block and `<think>` block removed (dropped if it reads
   like a plan or only introduces code), then an empty answer. A code block is never
   returned. The same logic covers a root timeout, where the call is bounded to one
   attempt with thinking off and a 60 s request timeout, and `protocol="tools"`, where a
   `final_answer` call or `FINAL` text is accepted.

Defects in the tasks. The generators were left unchanged, so these rows are scored as
the generators score them. The "answerable" columns above leave out the † cells.

- **Multivac's key never matches its question.** *(Fixed after this run: the target is now picked once; see `evals/independent/fixed/round2/`.)* `get_question()` and `get_answer()`
  each call `rng.choice` separately, so the key describes a different requirement from
  the one asked about. It mismatched in all 18 seed × size combinations checked. The
  bug is in the original, in the author's fix and in the MiniMax fix. `check.py` only
  tests `score(truth) == 1`, so it passed. In the rows we read, both modes answered about
  the requirement that was asked for.
- **TheDixieFlatline's answer is sometimes absent from the context.** *(Fixed after this run by its author: starting offices are now stated.)* The starting
  offices are never written into the context. If the final holder never moved or
  confirmed an office, the answer cannot be found. That happened in 3 of the 5 cells
  run: seed 0 small and medium, and seed 1 small.
- **SELMA's "Unassigned" key can contradict the text.** *(Fixed after this run: unassignment now emits an email.)* A random `unassign` event
  produces no email, so in 3 of the 5 cells run (seed 0 large, seed 1 small and medium)
  the key is "Unassigned" while the latest dated email names a lead. Both modes named
  that lead.
- **MasterControl's scorer rejects a name written inside a sentence.** *(Fixed after this run, along with unformatted amounts like `39195`.)* Its name regex
  runs with `IGNORECASE`, so `"Priya Patel was the only employee flagged…"` matches as
  one long "name", and a correct answer gets 0.5. That is MasterControl small seed 0
  for rlm. The cell is counted as answerable and the 0.5 stands.

**Verdict.** On tasks written by other models, the harness does not match the
self-authored results. Below the window, it is worse than just prompting the model.
Above the window, it is the only way to get an answer at all, but it gets one on only
about half of the answerable medium cells and a fifth of the large ones. Its answers
are reliable on tasks that a few greps can solve, and weak on multi-document
reconciliation. The clear levers are the turn budget and getting Qwen to delegate
reading to `llm_query`, plus the two forced-finish bugs (since fixed). Any change to those must be
measured on a fresh seed or new tasks, not on these rows.

#### Re-run after fixes (458e2f7)

**Frozen harness: commit `458e2f76c29ce668f898cc39d15b0ae6a8eb087c`.** We re-ran the same
grid once the defects found above were fixed. Two things changed since the first run:

- **The harness:** both forced-finish bugs were fixed (PR
  [#34](https://github.com/CryptoJones/ReCLamO-Harness/pull/34)). The forced finish now
  always asks the model once, shows it the REPL state, and never returns code. Batch
  metadata records `src/reclamo/{client,parsing,prompts,rlm}.py` as changed from
  `e17580f`. Nothing else changed.
- **The tasks:** four defects were fixed (PR
  [#35](https://github.com/CryptoJones/ReCLamO-Harness/pull/35)): the Multivac key, the
  missing starting offices in TheDixieFlatline, SELMA's unassignment email and
  MasterControl's scorer. GLaDOS, SHODAN, Cerebex and Neuromancer are unchanged, and for
  them every seed × size produced the same context and key as in the first run.

Everything else was the same as the first run: the default `pluto` profile, the fence
protocol, depth 1, 20 turns, `max_timeout=900` s and `run_eval.py` unchanged. Nothing was
tuned. The grid was also the same: 8 tasks × small/medium/large at seed 0, plus seed 1 for
small and medium, for 80 rows. Batches ran one task × size at a time under the pluto lock,
all small, then medium, then large. The run took 3 h 38 min on 2026-10-07/08. Raw rows are
in `runs/independent-rerun-20261007.json`, with one trajectory per rlm row in `runs/`
(not in git).

Each cell shows seed 0 / seed 1. The first run's **†** cells were tasks whose key could not
be reached. The fixes removed them for Multivac and TheDixieFlatline. **‡** marks SELMA
cells that are still ambiguous because of a remaining SELMA defect (see "Defects in the
round-2 tasks" below). The scores are what each generator's `score()` returned.

| Task (author model) | Size | rlm score | plain | rlm turns | rlm sub-calls | rlm s | rlm stop |
|---|---|---|---|---|---|---|---|
| GLaDOS (grok-4.6) | small | 1 / 0.80 | 1 / 1 | 20 / 20 | 0 / 0 | 541 / 330 | answer_dict / answer_dict |
|  | medium | 0.60 / 0.60 | does not fit (~148K tokens) | 20 / 20 | 0 / 0 | 215 / 316 | out of turns / out of turns |
|  | large | 1 | does not fit (~606K tokens) | 20 | 0 | 273 | out of turns |
| SHODAN (gpt-6-astra) | small | 0 / 0 (error) | 1 / 0 | 20 / – | 1 / – | 183 / 251 | out of turns / error |
|  | medium | 0 / 0 | does not fit (~89K tokens) | 20 / 20 | 0 / 22 | 216 / 995 | out of turns / out of turns |
|  | large | 0 | does not fit (~354K tokens) | 20 | 0 | 207 | out of turns |
| TheDixieFlatline (gemini-3.1-pro-high) | small | 0 / 0 | 1 / 1 | 11 / 14 | 0 / 0 | 167 / 267 | answer_dict / answer_dict |
|  | medium | 0 / 1 | does not fit (~99K tokens) | 11 / 18 | 0 / 0 | 155 / 257 | answer_dict / answer_dict |
|  | large | 0 | does not fit (~400K tokens) | 13 | 0 | 216 | answer_dict |
| Cerebex (glm-5.3-flash) | small | 0 / 0 | 0.50 / 1 | 20 / 20 | 0 / 1 | 306 / 465 | final / out of turns |
|  | medium | 0 / 1 | does not fit (~93K tokens) | 19 / 20 | 0 / 0 | 510 / 386 | answer_dict / final |
|  | large | 0 | does not fit (~373K tokens) | 20 | 4 | 345 | answer_dict |
| Neuromancer (deepseek-v4-flash) | small | 1 / 0 | 1 / 1 | 7 / 11 | 0 / 1 | 68 / 438 | final / answer_dict |
|  | medium | 0 / 1 | does not fit (~87K tokens) | 20 / 14 | 1 / 1 | 604 / 317 | answer_dict / answer_dict |
|  | large | 1 | does not fit (~351K tokens) | 20 | 0 | 366 | out of turns |
| SELMA (nemotron-3-super-120b-a12b) | small | 1 / 0‡ | 0 / 1‡ | 6 / 5 | 0 / 0 | 45 / 39 | answer_dict / final |
|  | medium | 1 / 0‡ | does not fit (~90K tokens) | 10 / 9 | 0 / 0 | 87 / 65 | final / answer_dict |
|  | large | 0‡ | does not fit (~358K tokens) | 7 | 0 | 57 | final |
| MasterControl (mistral-medium-3.1) | small | 1 / 1 | 1 / 1 | 8 / 10 | 0 / 0 | 78 / 94 | answer_dict / answer_dict |
|  | medium | 1 / 1 | does not fit (~87K tokens) | 11 / 10 | 0 / 0 | 176 / 186 | answer_dict / answer_dict |
|  | large | 1 | does not fit (~344K tokens) | 9 | 0 | 166 | answer_dict |
| Multivac (hermes-4-405b) | small | 1 / 0.50 | 1 / 0.50 | 5 / 6 | 0 / 0 | 38 / 32 | final / final |
|  | medium | 1 / 1 | does not fit (~106K tokens) | 7 / 7 | 0 / 0 | 61 / 52 | answer_dict / answer_dict |
|  | large | 1 | does not fit (~429K tokens) | 8 | 0 | 68 | answer_dict |

Accuracy by size in the re-run. A plain prompt that does not fit scores 0. The error row
scores 0.

| Size | Cells | rlm mean | rlm exact | plain mean | plain exact | plain does not fit | Cells without ‡ | rlm mean | rlm exact | plain mean | plain exact |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small (~60K) | 16 | 0.46 | 6/16 | 0.81 | 12/16 | 0/16 | 15 | 0.49 | 6/15 | 0.80 | 11/15 |
| medium (~300K) | 16 | 0.57 | 8/16 | 0.00 | 0/16 | 16/16 | 15 | 0.61 | 8/15 | 0.00 | 0/15 |
| large (~1.2M) | 8 | 0.50 | 4/8 | 0.00 | 0/8 | 8/8 | 7 | 0.57 | 4/7 | 0.00 | 0/7 |

Comparison with the first run, same cells (mean / exact):

| Size | rlm, first run | rlm, re-run | plain, first run | plain, re-run |
|---|---|---|---|---|
| small (~60K) | 0.38 / 5 of 16 | 0.46 / 6 of 16 | 0.59 / 9 of 16 | 0.81 / 12 of 16 |
| medium (~300K) | 0.36 / 5 of 16 | 0.57 / 8 of 16 | 0.00 (does not fit) | 0.00 (does not fit) |
| large (~1.2M) | 0.15 / 1 of 8 | 0.50 / 4 of 8 | 0.00 (does not fit) | 0.00 (does not fit) |

Split by whether the task changed (rlm over all three sizes; plain at small, the only size
where it fits):

| Tasks | rlm, first run | rlm, re-run | plain small, first run | plain small, re-run |
|---|---|---|---|---|
| Unchanged (GLaDOS, SHODAN, Cerebex, Neuromancer) | 0.33 / 5 of 20 | 0.40 / 6 of 20 | 0.81 / 6 of 8 | 0.81 / 6 of 8 |
| Fixed (TheDixieFlatline, SELMA, MasterControl, Multivac) | 0.33 / 6 of 20 | 0.62 / 12 of 20 | 0.38 / 3 of 8 | 0.81 / 6 of 8 |

Findings:

- **Most of the gain comes from the task fixes, not the harness.** The rlm improvement is
  concentrated in the four fixed tasks, where exact answers went from 6 of 20 to 12 of 20.
  Multivac went from 0 to exact on 4 of 5 cells, and its fifth cell is right but
  under-scored (see below). MasterControl is now exact everywhere. On the four unchanged
  tasks, rlm went from 5 to 6 exact out of 20, and plain scored exactly as before on all
  8 small cells. That rlm change is two exact cells gained (GLaDOS large and Neuromancer
  large) and one lost (Neuromancer small seed 1). The contexts were identical, so this
  is consistent with run-to-run sampling noise.
- **The forced-finish fixes did not rescue any answer.** There were 9 forced finishes
  (`forced_finish` events), all from running out of turns, against 15 in the first run.
  Of these, 8 had `source=model`: the forced reply contained a valid `FINAL(...)`. The
  other was `source=reply_text`. None used `answer_dict` or `variable`, and `shown` was
  empty in all 9, so no answer dict or answer variable existed to show. Two of the 9 were
  exact, the same count as the first run's 15:
  - **GLaDOS large** (`runs/20261008T071548Z-de1caa.jsonl`): the reply was a model
    `FINAL`.
  - **Neuromancer large** (`runs/20261008T073313Z-48c9be.jsonl`): the reply was
    `FINAL ≈ **$91,049.09**`, which does not parse as `FINAL(...)`. The new fallback kept
    its prose, the same total the first run lost to a stale `result` variable.

  This time, however, that trajectory made no `llm_query` call and set no `result`, and
  the reply contained no code. The old code would have returned the same text. Bug 1 (a
  stale variable) never had a variable to act on, and bug 2 (code returned as the answer)
  never had code to strip. The fixes are therefore untested by this run rather than shown
  to help. No answer contained a code block.
- **Below the window, plain still wins clearly.** At ~60K characters, plain was exact on
  12 of 16 cells and rlm on 6. Plain took a median 69 s for the chosen call (167 s for
  both variants), against 175 s for rlm. TheDixieFlatline is now answerable, and it shows
  the gap: plain was exact on both seeds, and rlm was wrong on both. On small seed 0,
  rlm traced the renames correctly. It then took an Auditor's "going to be moved to Room
  112 tomorrow" as the final location (`runs/20261008T044627Z-6d2fa3.jsonl`).
- **Above the window, the harness is still the only option, and it is better than in
  the first run.** It was exact on 8 of 16 medium and 4 of 8 large cells, against 5 of 16
  and 1 of 8 in the first run. It is reliable on MasterControl and Multivac (exact on
  every medium and large cell) and still never solves SHODAN (0 of 5). GLaDOS medium
  keeps getting 0.60: a wrong amount, or a right amount with no certifying member. Cerebex
  large was wrong despite 4 sub-calls.
- **The turn cap is still the main harness-side limit.** 15 of 40 rlm rows used all 20
  turns, and 9 of them ended in a forced finish (2 exact). SHODAN medium seed 1 made
  22 `llm_query` calls, then gave up with all-zero credits. Its forced reply says "the
  aggregation step never ran" (`runs/20261008T061131Z-c01315.jsonl`).
- **Qwen still rarely delegates.** 7 of 40 rlm rows made any sub-call, against 5 in the
  first run, and one row accounts for 22 of the 31 calls.
- **Protocol is still clean, with one aborted row.** 536 code executions produced
  1 syntax error and 8 execution errors, with 0 rejected finals and 7 protocol slips. One
  row, SHODAN small seed 1, is an **error** row (`runs/20261008T043757Z-64a70a.jsonl`):
  turns 13–15 raised a `SyntaxError` and then two `IndexError`s, and `max_errors=3`
  raised `RLMErrorLimit`. That exception ends the run with no forced finish, so 15 turns
  of REPL state produced no answer. This is a new harness finding. It is recorded here
  and not fixed.
- **`max_timeout` can overrun by a turn plus the forced finish.** SHODAN medium seed 1
  took 995 s against the 900 s cap. The deadline is checked when each turn starts. Turn
  20 started at 852 s and ended at 929 s, and the forced finish after running out of
  turns is not time-bounded (only the timeout path is). No run looped or stalled, and
  none had to be killed.

Defects in the round-2 tasks. The scores above stand as the round-2 generators compute
them. The round-3 audit found both of these independently, and they were fixed on `main`
in PR [#46](https://github.com/CryptoJones/ReCLamO-Harness/pull/46), which merged during
this run's large phase. This run used the round-2 versions pinned at `458e2f7` throughout:
`run_eval.py` checks each generator's sha256 against that manifest.

- **SELMA's round-2 fix is incomplete (‡).** The key follows the emails' order in the
  document, but each email's displayed `Date:` is a random day within the event's year
  (`_rand_date(rng, year, year)`). The latest-dated email can therefore contradict the
  key. In all three "Unassigned" cells that were run, the latest-dated AI Ethics email
  assigns a lead. These are small seed 1, medium seed 1 and large seed 0, the same three
  cells as the first run's †. In large seed 0, for example, "Position Now Unassigned" is
  dated 2032-01-20 and an assignment to Taylor Jackson is dated 2032-04-13. rlm sorted
  by date and answered Taylor Jackson (`runs/20261008T073921Z-ab1184.jsonl`). Over seeds
  0–9, 12 of 30 seed × size cells have this conflict. The round-2 self-test passed
  because it finds the last email by position, not by date.
- **Three scorers reject correct answers written in markdown or as phrases.** This is the
  same kind of defect that MasterControl had:
  - SELMA splits the answer on whitespace, so `**Skyler Martin**` keeps its asterisks and
    scores 0. On SELMA small seed 0, plain's thinking variant gave that correct answer
    in bold. Its no-thinking variant said "Unassigned", so the cell scored 0.
  - Multivac's status regex rejects both "status is **Blocked**" and
    "**Status:** Blocked". On Multivac small seed 1, both modes gave the correct status
    and full description and scored 0.50.
  - GLaDOS's outcome check rejects "DID pass". On GLaDOS small seed 1, rlm had the right
    amount and name and scored 0.80.

**Verdict.** After the fixes, the picture is the same in kind and better in degree.
Below the window, the plain model is still clearly better: 12 exact against 6. Above it,
the harness answers about half the cells exactly, where plain answers none: 8 of 16
medium and 4 of 8 large, up from 5 and 1. The improvement comes from repairing the
tasks; on unchanged tasks it is within noise. The forced-finish fixes were not
exercised. The open levers are the same as before: the 20-turn budget, delegation to
`llm_query`, and multi-document reconciliation (SHODAN). Two new harness questions came
up: whether `max_errors` should end in a forced finish rather than an exception, and
whether the forced finish should be time-bounded. Both need measuring on new seeds, not
on these rows. These numbers are also for the round-2 task set. The round-3 set in PR #46
changes the keys and scorers of all eight tasks, so it needs its own run.

### Smoke run (self-authored tasks)

These tasks, like the benchmark, protocol and depth-2 tasks below, were written by the
harness's own authors. For tasks written by other models, see
[Independent evaluation](#independent-evaluation-tasks-written-by-other-models).

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

### Benchmark: harness vs plain model, 3 seeds

The tasks in this benchmark were written by the harness's own authors. On tasks written
by other models the harness does much worse; see
[Independent evaluation](#independent-evaluation-tasks-written-by-other-models).

[#19](https://github.com/CryptoJones/ReCLamO-Harness/issues/19). `examples/bench.py
--profile pluto --seeds 3`, run 2026-10-07 against the same server and default profile
as above. Raw rows: `runs/bench-20261007T094811Z.json` (not in git).

What each mode means:

- **rlm** is the harness.
- **plain** is one chat call with the whole context in the prompt.
- **does not fit** means the plain prompt would not fit pluto's usable window, so the
  plain model cannot attempt the task. The usable window is 28,672 tokens: 32K resident
  KV minus an output reserve.

The token estimate counts one token per digit and 3.5 characters per token otherwise.
Each plain run is the better of two variants, so the baseline is not penalised by a
cut-off: thinking on with a 16K output cap, and thinking off.

| Task | Size | Mode | Result over 3 seeds | Median s | Median sub-calls |
|---|---|---|---|---|---|
| needle | 2,000 lines | rlm | 3/3 found | 13.7 | 0 |
| needle | 2,000 lines | plain | 3/3 found | 0.6 | – |
| needle | 10,000 lines | rlm | 3/3 found | 13.2 | 0 |
| needle | 10,000 lines | plain | does not fit (~74K tokens) | – | – |
| needle | 100,000 lines | rlm | 3/3 found | 16.3 | 0 |
| needle | 100,000 lines | plain | does not fit (~1.5M tokens) | – | – |
| needle | 1,000,000 lines | rlm | 3/3 found | 15.9 | 0 |
| needle | 1,000,000 lines | plain | does not fit (~16M tokens) | – | – |
| oolong_lite | 100 tickets | rlm | exact 3/3 | 84 | 4 |
| oolong_lite | 100 tickets | plain | exact 3/3 | 85 | – |
| oolong_lite | 300 tickets | rlm | exact 3/3 | 117 | 3 |
| oolong_lite | 300 tickets | plain | exact 3/3 | 292 | – |
| oolong_lite | 1,000 tickets | rlm | exact 2/3; one seed off by 34 | 380 | 16 |
| oolong_lite | 1,000 tickets | plain | 2 of 3 do not fit; the one that fit was wrong (total error 360) | – | – |
| longdoc_qa | 100 sections | rlm | 9/9 questions | 38 | 0 |
| longdoc_qa | 100 sections | plain | 9/9 questions | 82 | – |
| longdoc_qa | 300 sections | rlm | 9/9 questions | 80 | 0 |
| longdoc_qa | 300 sections | plain | does not fit (~53K tokens) | – | – |

Findings:

- **Where the context fits, the plain model is just as accurate.** At 100 and 300
  tickets, the 100-section QA and the 2,000-line needle, plain was exact every time. The
  harness is not smarter on small inputs.
- **Where it doesn't fit, only the harness can answer.** That covers the needle from
  10K to 1M lines, 1,000 tickets and 300 sections. The harness found the needle all 12
  times at up to ~16M estimated tokens, in about 16 s each. It answered all 18 QA
  questions and got 1,000 tickets exact on 2 of 3 seeds.
- **The harness is often faster even when plain fits.** It took 117 s against 292 s at
  300 tickets, and 38 s against 82 s on the 100-section QA. It keeps the root prompt
  small instead of thinking over the whole document in one call. The exception is the
  tiny needle, where plain answers in under a second.
- **The first plain baseline was unfair.** Two of its three 100-ticket failures were
  cut-offs: thinking ran into the output limit. The best-of-two rule above replaced it.
  With the rule in place, plain is 3/3.
- **Sub-calls stayed small.** 0 to 16 per run. 16 was at 1,000 tickets, still about 60
  tickets per call rather than one per ticket.
- **The one miss** was oolong_lite at 1,000 tickets, seed 2, total error 34. The other
  two seeds were exact. This is the size where per-batch classification errors start to
  add up.
- **Caveats.** These are synthetic tasks written by the harness's authors. See
  [#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22) and
  `evals/independent/` for the tests written by others. A `plain_truncated` mode (the
  head of the context, cut to fit) exists in `bench.py` but is not reported: an early
  version under-estimated digit-heavy text and sent prompts too long for the 300 s
  request timeout. It is fixed, but has not been re-run.

### Protocol: fenced code vs tool calls

[#20](https://github.com/CryptoJones/ReCLamO-Harness/issues/20). `--protocol tools`
(config `protocol = "tools"`) has the root model act through OpenAI-style function
calls instead of fenced code and `FINAL(...)` text. `execute_python(code)` returns the
REPL output, with the same truncation and sub-call caps. `final_answer(answer=... |
variable=...)` finishes; it takes exactly one of the two, and `variable` must exist.

The history stays append-only. Each turn adds the assistant message with its
`tool_calls`, then one `tool` message per call in call order, then a user message with
any notes and the next `Turn i/N` line. The guards from the fence protocol still apply:
a final sent next to code is rejected, a plan-like final is rejected once, the
re-verify and decompose nudges fire, and the forced finish and the timeouts work the
same way.

A reply with no tool call gets a nudge. A fenced block or a `FINAL(...)` written as text
is honoured once and logged as a protocol slip. The fence prompt is unchanged. Strata
returns structured `tool_calls` for Qwen3.8-Flash-Next, so there is no text-parsing
fallback.

Run 2026-10-07 on the same server and profile as above. Both protocols were
interleaved per seed, and each row took the pluto lock on its own. `bench.py --modes rlm
--protocol {fence,tools} --seeds 3` gives the raw rows in
`runs/proto-bench-20261007.json` (not in git). "Syntax errors" counts executed blocks
whose error was a `SyntaxError`. "Slips" counts the protocol slips above, plus fence
replies with neither code nor a final.

| Task | Size | Protocol | Result over 3 seeds | Final rejections | Slips | Syntax errors / execs | Median turns | Median s |
|---|---|---|---|---|---|---|---|---|
| needle | 100,000 lines | fence | 3/3 found | 0 | 0 | 0/6 | 3 | 14.9 |
| needle | 100,000 lines | tools | 3/3 found | 0 | 0 | 0/6 | 3 | 18.1 |
| oolong_lite | 300 tickets | fence | exact 3/3 | 0 | 0 | 0/17 | 7 | 121 |
| oolong_lite | 300 tickets | tools | exact 3/3 | 0 | 0 | 0/21 | 7 | 244 |
| oolong_lite | 1,000 tickets | fence | exact 3/3 | 0 | 0 | 0/27 | 10 | 454 |
| oolong_lite | 1,000 tickets | tools | exact 3/3 | 0 | 0 | 0/14 | 5 | 304 |
| longdoc_qa | 300 sections | fence | 6/9 questions (one seed out of turns) | 0 | 0 | 0/44 | 15 | 134 |
| longdoc_qa | 300 sections | tools | 9/9 questions | 0 | 0 | 0/30 | 11 | 94 |

The independent eval set (`evals/independent/fixed/active/`, size medium, seed 0) was
run as a protocol comparison only; nothing was tuned on it, because it is reserved for
the frozen [#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22) eval. Raw
rows are in `runs/proto-indep-20261007.json`, with `max_timeout=900`.

| Protocol | Mean score (8 tasks) | Exact | Final rejections | Slips | Syntax errors / execs | Median turns | Median s |
|---|---|---|---|---|---|---|---|
| fence | 0.28 | 2/8 (MasterControl, SELMA) | 0 | 2 (no code, no final) | 0/113 | 19.5 | 231 |
| tools | 0.40 | 3/8 (MasterControl, SELMA, Neuromancer) | 0 | 0 | 0/125 | 19 | 209 |

Findings:

- **The protocol errors #20 set out to remove do not occur any more.** Over 24 bench
  runs and 16 independent runs, neither protocol produced a syntax error or a rejected
  final. Qwen never slipped out of the tools protocol: no text-only replies, no fenced
  code, no malformed arguments. The fence protocol had two turns with neither code nor
  a final, both on independent tasks the model failed anyway. The prompt and parser
  tuning in #7 already removed what the tools protocol would have fixed.
- **Accuracy is the same within noise.** Each protocol's extra wins come from a single
  run. Fence lost one longdoc_qa seed by searching for 20 turns, after which the forced
  finish returned its reasoning text. That task got 9/9 with fence in the #19
  benchmark. Tools won Neuromancer only through the forced finish, which picked up an
  answer already sitting in a REPL variable. Both protocols failed the same five
  independent tasks; three of them ran out of turns.
- **Speed is mixed.** Tools was faster on longdoc_qa (94 vs 134 s), on 1,000 tickets
  (304 vs 454 s) and on the independent set (209 vs 231 s). It was twice as slow on 300
  tickets (244 vs 121 s): it chose 50-ticket batches and a verification pass where
  fence used three 100-ticket calls. That is a strategy difference, not a protocol
  error. Tool turns also cost more prompt tokens, because of the tool schemas and the
  JSON-escaped code.
- **The default stays `fence`.** Tools is not clearly better: it has no error rate to
  improve and it ties on accuracy. `--protocol tools` is supported and tested for
  servers or models whose fenced-code output is less reliable. Its stats show up in
  every trajectory's `final` record and in bench rows, so the comparison can be re-run
  cheaply. With three seeds and one run per independent task, these are observations,
  not significance tests.

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
