# Frontier replication kit: GPT-5 RLM vs plain GPT-5

This kit reruns the core claim of *Recursive Language Models* (Zhang, Kraska and Khattab,
[arXiv 2512.24601](https://arxiv.org/abs/2512.24601)) with the paper's own model pairing
and settings, on eight long-document tasks the paper's authors never saw. Issue
[#120](https://github.com/CryptoJones/ReCLamO-Harness/issues/120). The test plan is
pre-registered in [`evals/TEST-PLAN.md`](../TEST-PLAN.md) §1j.

The claim under test: GPT-5 answers questions about long documents better when it works
through a Python REPL with GPT-5-mini sub-calls (the RLM) than when it reads the whole
document at once.

**This file is written so that a coding agent can run the experiment end to end.** A
person needs to do only two things: provide an OpenAI API key, and set a spending limit.

---

## What runs

| Arm | Profile | What it is |
|---|---|---|
| `rlm` | `gpt5-rlm` | GPT-5 root, GPT-5-mini sub-calls, the paper's prompt and limits |
| `plain` | `gpt5-plain` | GPT-5 reads the whole document in one call |
| `mapreduce` (large only) | `gpt5-plain` | GPT-5-mini reads fixed chunks, GPT-5 combines the answers |

- **Tasks:** 8 synthetic task families in `evals/independent/fixed/active/`. Each question
  has one exact answer, graded by that task's own program, not by a model.
- **Sizes:**
  - small: ~60K characters, ~20K tokens;
  - medium: ~300K characters, ~90–150K tokens;
  - large: ~1.2M characters, ~340–610K tokens.

  No large document fits GPT-5's 272K-token input window. That is why large also runs the
  map-reduce baseline: plain GPT-5 scores zero there by construction.
- **Stages:**
  - `pilot`: seeds 4–11, which is 64 pairs per size.
  - `full`: seeds 4–43 at small and medium (320 pairs each) and 4–23 at large (160 pairs).

  The full run resumes the pilot's files, so pilot rows are part of the full sample.
- **Expected cost:** about $40–80 for the pilot and $350–600 for the full run. Use the
  OpenAI usage dashboard as the real figure.
- **Expected time:** a few hours for the pilot and about a day for the full run, at
  tier-2+ rate limits.

## Same as the paper, different, and why

| Setting | Paper (§3.2, App. C.1) | This kit | Same? |
|---|---|---|---|
| Root model | GPT-5, medium reasoning, default sampling | same | yes |
| Sub-call model | GPT-5-mini | same, medium reasoning | yes |
| System prompt | App. C.1 (1a) | (1a) word for word (`UPSTREAM_GPT5_SYSTEM_PROMPT`, checked by test) | yes |
| Message layout | alexzhang13/rlm v1.0.0: context metadata as an assistant turn, per-turn user prompt | same (`planner_style = "upstream-rlm-gpt5"`) | yes |
| REPL output shown per turn | 20,000 characters | 20,000 | yes |
| Root turns | 30 | 30 | yes |
| Input window | 272K tokens | 272K (400K minus a 128K output reserve) | yes |
| Recursion depth | 1 (sub-calls are plain LM calls) | 1 | yes |
| Tasks | OOLONG, BrowseComp-Plus, CodeQA, S-NIAH | 8 new synthetic families | **no:** the point is to test on tasks the method was not developed on |
| Plain baseline prompt | no system prompt | a one-line "careful analyst" system prompt (`examples/bench.py`) | **no:** kept identical to the earlier local runs so results line up |
| Sub-call caps | none | 256 per run, 64 per code block | **no:** a runaway guard; the paper's GPT-5 runs used far fewer |
| Per-question limits | none stated | 1 hour, 4M tokens (~$5) | **no:** a runaway guard |
| At the turn cap | upstream asks for a final answer | the harness asks for a final answer | similar |
| Sandbox | local `exec` | a subprocess REPL | equivalent for these tasks |
| Map-reduce baseline at large | the paper compares against summary and retrieval agents | fixed-chunk map-reduce | **no:** the closest baseline already in this repo |

## Requirements

- macOS or Linux, `git`, `bash`, Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).
- An OpenAI API key with access to `gpt-5` and `gpt-5-mini`, in `OPENAI_API_KEY`.
- **A hard monthly budget on the OpenAI project** (platform.openai.com → Settings →
  Limits). The run script also has a cost guard, but the dashboard limit is the one
  that cannot be bypassed.
- **Isolation:** the model writes Python that runs in a subprocess on this machine. Run
  the kit in a VM, a container or a throwaway user account. Docker users can set
  `sandbox = "docker"` in both profiles instead.

## Steps (for the agent)

Do these in order. Do not edit code, prompts, profiles or tasks. If something seems to
need an edit, stop and report it instead: an edited run is not the pre-registered run.

1. **Get the code at the pinned commit.**
   ```bash
   git clone https://github.com/CryptoJones/ReCLamO-Harness.git
   cd ReCLamO-Harness
   git checkout <COMMIT>   # the commit named in the email or issue #120
   uv sync
   ```
2. **Check it.** Every test must pass. The Docker tests skip when Docker is absent.
   ```bash
   uv run pytest -q tests/test_gpt5_kit.py
   uv run pytest -q
   ```
3. **Check the key without printing it.** Make one call:
   ```bash
   uv run reclamo ping --profile gpt5-rlm --profiles evals/gpt5-replication/profiles.toml
   ```
   Success means no error line. `reply` may be empty and `thinking: no` is expected: ping
   caps the probe at 16 tokens, which GPT-5 can spend on reasoning, and the OpenAI API
   does not return reasoning text.
4. **Dry run:** sizes and fit decisions, no model calls.
   ```bash
   uv run python evals/independent/run_eval.py --profiles evals/gpt5-replication/profiles.toml \
     --profile gpt5-plain --modes plain --sizes small,medium,large --seed-list 4 --dry-run
   ```
   Expect every small and medium document to fit and every large one not to fit.
5. **Pilot.** Pick the cap with the person paying.
   ```bash
   OPENAI_API_KEY=... CAP_USD=100 nohup evals/gpt5-replication/run.sh pilot > runs/exp-gpt5-pilot.log 2>&1 &
   ```
   The cost guard prices every token at GPT-5's uncached rate. That overstates the real
   cost by up to 3× (GPT-5-mini and cached input are cheaper). Set the cap with that in
   mind.
6. **Pilot go / no-go.** Decide on these checks only. Do not look at scores.
   - After the reruns, fewer than 5% of rows are errors (`runs/exp-gpt5/quarantine/`).
   - No arm has more than 25% of its rows stopped by `error_limit` (repeated code or parse
     errors). That pattern means a harness problem, not a model result.
   - Spend per pair is within 2× of the estimate above.

   If any check fails, stop and send back what you have.
7. **Full run** with the agreed cap:
   ```bash
   OPENAI_API_KEY=... CAP_USD=600 nohup evals/gpt5-replication/run.sh full > runs/exp-gpt5-full.log 2>&1 &
   ```
   The run is finished when the log's last line is `GPT5DONE full`. If it stops early
   (rate limits, a crash), run the same command again: it resumes, and rows that already
   finished are not re-run.
8. **Analyse** with the pre-registered analysis:
   ```bash
   python3 evals/gpt5-replication/analyze.py runs/exp-gpt5 > runs/exp-gpt5/report.md
   ```
9. **Send back** `runs/exp-gpt5/` as a tarball. It contains `rlm.json`, `plain.json`,
   `mapreduce.json`, `report.md`, `commit.txt`, `spend.txt`, `quarantine/` and `traj/`
   (the full transcripts), plus the two logs. **It contains no keys.** Check with
   `grep -r "sk-" runs/exp-gpt5 | head` before sending.

## Rules for the run

- **Never** print, log or commit the API key.
- **Never** delete a row because of its score. Only error rows are re-run, and the
  script does that itself.
- One look at the results, after the full run. The pilot decides only whether the
  pipeline works.
- Report a stopped or partial run as it is, with no substitute rows.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
