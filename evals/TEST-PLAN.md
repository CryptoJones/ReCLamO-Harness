# ReCLamO evaluation test plan

This is a living plan. It lists what the evaluation measures, in what order, and how each result
will be judged. It deliberately holds no results; those live in the README Results sections
and in `runs/`.

Last revised 2026-10-09. Sources: CJ's review, the paper re-read (arXiv 2512.24601 v1–v3, the
author's blogs, upstream `rlm`), and a roundtable of 8 non-Anthropic models (GLM, Mistral,
DeepSeek, Nemotron, GPT, Gemini, Hermes, Qwen; Grok's lane failed to authenticate).

## 0. Rules that apply to every phase

- **Pre-register.** Before a phase runs, write its hypothesis, arms, sample size, metric, test
  and stopping rule into this file. Results are judged against what was written down in
  advance.
- **Frozen exam.** Never tune prompts or settings on the questions used to evaluate. A change
  is judged only on fresh seeds or new tasks.
- **One change at a time.** An arm differs from its control in exactly one factor. Where that
  is impossible, say which factors are confounded.
- **Same questions for every arm.** Comparisons are paired: every arm answers the identical set.
- **Report completion separately from accuracy.** Every row records how the run ended: answered,
  forced finish, turn cap, time limit, error limit, context overflow, provider error, or not
  run. Report the completion rate, accuracy over all rows, and accuracy over completed rows.
  Provider and transport failures are `not_run`, never a score (#56).
- **Statistics.** Report exact counts and mean scores with 95% confidence intervals. Paired
  comparisons use McNemar (exact) and a paired bootstrap on means. A difference is "real" only
  if the test says so; otherwise report it as "no detectable difference".
- **Record cost and speed** for every row: tokens in and out, sub-calls, wall-clock time.
  Report the median and 95th percentile.
- **Log what each arm actually received:** tokenized input length, the context and window
  settings, stop reasons, how many characters of REPL output were clipped, and the code
  commit, profile, prompt version and Strata config.
- **Data safety.** Raw rows and trajectories are continuously backed up off-machine
  (`~/bin/reclamo-backup.sh`). Never overwrite a results file: rescoring writes a new file.

## 1. Sample size, pairing and stopping (revised 2026-10-09 after a sample-size roundtable)

**Power target.** The primary comparisons are paired: every arm answers the same questions, and
McNemar's exact test uses only the questions where the arms disagree. Our pilot measured a
discordant rate of q ≈ 0.30: harness v0.1 vs plain-128K had 9 of 30 pairs disagree (7
harness-only correct, 2 plain-only); v0.1 vs v0.2 had 8 of 32. With
n ≈ (1.96 + 0.84)² · q / δ² (α = .05 two-sided, power .80):

| Detectable difference δ | Pairs needed per comparison per size (q = 0.30) | Seeds at 8 tasks |
|---|---|---|
| 10 points | ~240 (~320 with the interim looks below) | ~30–40 |
| 5 points | ~940 (~1,260 with interim looks) | ~120–160 |

So 64 per cell detects only very large effects (~25+ points). **Target: 320 pairs per primary
comparison per size**, enough for a 10-point effect with three looks. Treat 5-point effects as
out of reach on pluto alone. (Six of eight roundtable models made arithmetic or formula errors;
the planning formula above follows SHODAN/GPT's derivation and our measured q.)

**Rules agreed by all eight roundtable models:**
- **Strict pairing.** Every harness question is also answered by plain. Extra plain-only seeds may
  be run to estimate baseline accuracy, but they never count toward paired n.
- **Task is a random effect.** Variance is dominated by task generator, so more seeds of the same 8
  tasks hit diminishing returns: effective n = N / (1 + (m−1)·ICC). Report per-task effects, a
  task-weighted average, and a cluster bootstrap by task. **Generalizing beyond these tasks needs
  more generators: target ≥ 16 tasks** (new generators written by outside models, as before).
  Seven of eight models flagged this.
- **Replicates:** about 10% of runs are same-question repeats (2–3 runs on a preselected balanced
  subset), to measure sampling noise. They are nested within questions and never added to n.
- **Separate models are separate experiments.** OpenRouter `qwen/qwen3.8-flash` (or any variant)
  is a replication arm with its own pairing, analysed separately, never pooled with pluto's runs.
- **Pre-registered stopping:** three looks at about ⅓, ⅔ and all of the target n (≈ 107, 213,
  320 pairs). Reject only at two-sided exact McNemar p ≤ .0167 at any look (Bonferroni), or use
  O'Brien–Fleming boundaries (|z| > 3.0, 2.0, 1.96). Fix one primary comparison per size before
  the first look: **harness v0.1 vs plain-128K**. Everything else is secondary and reported with
  that label.

**Question variety:**
- **Paraphrases:** 3–4 rewordings of each question (formal, casual, indirect, messy), written by
  a model not under test, with the key unchanged. Measure answer consistency; these are a
  robustness check, not extra n.
- **Current grid:** 8 tasks × seeds 2–9 = 64 per cell (running). It extends in rolling batches
  toward 320 pairs (seeds 2–41) for the primary comparison at small and medium; large uses
  harness arms only.

## 2. Validity checks (run first; they can invalidate everything else)

1. **The document is causally needed.** Each check runs on a subset per task:
   - **question only:** no document;
   - **evidence deleted:** the deciding fact removed;
   - **decoy chain:** a broken chain that ends in a plausible wrong answer;
   - **counterfactual twin:** one deciding fact changed, so the key must change.

   A setup that scores without the evidence, or doesn't track the twin, is pattern-matching
   the generator. *(SHODAN, TheDixieFlatline, Cerebex)*
2. **Answer keys are independently verified.** Hand-reconstruct the answer from the rendered
   documents for at least 3 seeds per task per size. Check uniqueness, chronology and which
   correction wins. *(Cerebex, SHODAN)*
3. **Human grader check.** Hand-grade a random 10% of graded answers per arm. Report agreement
   with the programmatic score and every disagreement. Include runs where the harness scored
   below plain. *(Multivac, Neuromancer)*
4. **Recoverable answers.** For each failed run, extract any answer the model reached but failed
   to submit (format slips, the turn cap). Report delivered accuracy and recoverable accuracy.
   *(SHODAN, TheDixieFlatline, Cerebex)*

## 3. Ablations: attribute every effect to one cause

1. **v0.1 vs v0.2, decomposed:** prompt × turn cap × REPL output limit, changed one factor at a
   time, plus a check at matched total compute (tokens including sub-calls). Post-hoc: truncate
   v0.2 logs to 2K output and re-score. *(Cerebex, SELMA, SHODAN, Proteus)*
2. **What part of the harness helps:** REPL only (no sub-calls), REPL plus `llm_query`, and a
   plain iterative solver, all at equal total budget. *(SHODAN)*
3. **Prompt-wording sensitivity:** 3–5 harness prompt variants at a fixed strategy. *(Multivac,
   Neuromancer, MasterControl)*
4. **Context growth:** log the planner's context fill on every turn, and plot accuracy against
   final-turn depth. *(TheDixieFlatline)*
5. **Document access:** a raw string vs pre-segmented sections plus a search helper. *(Multivac)*

## 4. Diagnosing delegation

1. **Oracle interventions:** on a fixed subset,
   - give the readers the correct evidence chunks;
   - separately, replace reader outputs with verified intermediate answers.

   This shows whether failures come from choosing the evidence, reading it, or combining it.
   *(SELMA, SHODAN, Multivac, Neuromancer)*
2. **Score each sub-call:** grade every `llm_query` input and output with the task's facts, so
   you can see where the signal is lost. *(TheDixieFlatline, Neuromancer)*
3. **Sub-model pairing:** the same model in both roles vs a strong planner with a small reader vs
   a small dispatcher with a large reader (the RunPod 3-arm experiment). *(Cerebex; CJ's
   dispatcher idea)*

## 5. Coverage: what the tests contain

1. **Large documents** (~1.2M chars): 64 questions, harness arms only (plain cannot fit).
2. **Unanswerable questions:** the key fact deleted, mixed 50/50 with answerable ones; the right
   answer is "cannot be determined"; abstention is scored and false answers are counted.
3. **Mixed piles:** 2–3 task documents combined, with one question from each, plus
   multi-question runs over one pile.
4. **Size sweep:** 16K, 32K, 64K, 128K, 256K, 1M tokens, to find the crossover.
5. **Length without added difficulty:** the same deciding records plus irrelevant padding only.
   Separately vary chain depth (3 vs 8 hops) and distractor similarity at fixed length.
   *(SHODAN, Neuromancer)*
6. **Evidence position** (start, middle, end), and evidence placed on purpose across the
   harness's chunk boundaries. *(Proteus)*
7. **Generator-convention sensitivity:** the same facts with different formatting, ID styles,
   record order (including shuffled) and correction wording. Break results down by the
   generator's author model. *(SHODAN, SELMA, MasterControl, Proteus, Cerebex)*
8. **Reasoning types:** add aggregation and counting, conditional arithmetic, comparison, and
   long-output tasks (OOLONG-style), alongside today's multi-hop chains. *(Neuromancer)*
9. **Contradiction handling:** documents with conflicting statements; check whether a reader's
   error propagates or is caught. *(Neuromancer)*
10. **Real documents:** ACM papers, codebases, email threads, with hand-written keys.
11. **Paper benchmark reproduction:** OOLONG and/or BrowseComp-Plus, compared with the published
    numbers.

## 6. Baselines and models

- **Baselines:** plain (32K and 128K), retrieval (BM25 top-k then answer), and a
  summarize/compaction agent, as in the paper.
- **Models:** Flash-Next (local), at least one frontier model as a ceiling, Laguna, Llama 3.3
  70B, and the paper's RLM-Qwen3-8B under its native conditions (32K window, 20K outputs,
  Qwen3-8B reader).

## 6a. The paper's fine-tuned 8B: replicate the fine-tuning claim

The paper's 8B result is that **fine-tuning helps**: Qwen3-8B fine-tuned on RLM trajectories
(RLM-Qwen3-8B, `mit-oasys/rlm-qwen3-8b-v0.1`) beats base Qwen3-8B in the same harness. Our
earlier 8B run (1/16 small, 4/16 medium, 0/8 large) tests neither that claim nor the model's
native conditions, so it is a pilot only.

- **Arms** (same harness, same questions, `planner_style = upstream-rlm-v0`):
  1. base Qwen3-8B as planner;
  2. RLM-Qwen3-8B as planner;
  3. optionally, base vs fine-tuned with prompt v0.2 (`reclamo` style), to test whether the
     fine-tuning transfers outside its training format.
- **Native conditions,** matched to how it was trained (App. A):
  - a 32K window and 20,000-char REPL output;
  - the reader is Qwen3-8B (as in the paper's training), with a Flash-Next-reader variant as a
    separate arm;
  - reader sub-calls capped to fit the reader's window (the 8B's own prompt advertises up to
    ~100K chars).
- **Paper benchmark check:** run both arms on the paper's own evaluation tasks where available,
  and compare with the published base vs fine-tuned numbers (v2 Table 1) before our tasks.
- **Hardware:** the 8B at 32K needs more memory than makemake had spare. Options: a
  lower-bit quant locally (a stated deviation), or RunPod once the dataset gate opens
  (DECISION note, 2026-10-09).
- **Metric:** paired exact and mean, with confidence intervals; fine-tuned vs base is the
  headline contrast; sub-call counts and early-commit rate are diagnostics.

## 6b. Model identity and architecture-appropriate settings (added 2026-10-09)

**The main model is not Qwen3.** pluto's GGUF metadata (`Qwen3.8-Flash-Next-UD-Q4_K_XL`) reads
`general.architecture = qwen4exp` and `general.description = "A Preview of the Qwen4
Architecture"`: a 512-expert MoE with 10 experts active, 48 layers, 262,144-token context,
quantized by Unsloth and abliterated by Huihui.ai.

- **Implication for claims:** harness vs plain and v0.1 vs v0.2 comparisons are within-model and
  stay valid. Any comparison with the paper's Qwen results (Qwen3-Coder-480B, Qwen3-8B,
  RLM-Qwen3-8B) is **cross-architecture** and must say so. Section 6a (base vs fine-tuned
  Qwen3-8B) is the same-architecture replication anchor.
- **Sampling mismatch:**
  - the GGUF's embedded defaults are `temp = 1.0, top_p = 0.95, top_k = 20`;
  - every Flash-Next run so far used Qwen3 model-card presets (root 0.6 / 0.95 / 20 / min_p 0;
    sub 0.7 / 0.8 / 20 / presence_penalty 1.0).

  Add an ablation that runs the primary comparison with the model's own sampling defaults vs our
  presets. Report which settings each published number used.
- **Chat template and thinking switch:** verify that `chat_template_kwargs.enable_thinking` and
  `reasoning_effort` behave as assumed on qwen4exp (Strata's template). Record the template hash
  per run.
- **Abliteration:** the model is an abliterated (refusal-removed) variant, which can change
  behaviour beyond refusals. Note it as a threat to validity. If a non-abliterated qwen4exp
  build is available, run a small paired check.
- **Every model entry** in results tables names its architecture, quantization, abliteration
  status and serving stack.

## 7. Reporting

- **Per arm:** completion rate, accuracy over all and over completed rows, confidence
  intervals, cost, latency.
- **Breakdowns:** per task and per generator author; a failure taxonomy (wrong evidence,
  misread, bad combination, early commit, turn cap, format, crash).
- **Every number names** its code commit, test-set version, grader version, seeds and
  profile.
- **Pre-registered** hypotheses and their outcomes, including the ones that failed.

## 8. Order of work

1. **Running now:** the main grid on seeds 4–9 (small, medium), then 64 large questions.
2. **Section 2:** validity checks.
3. **Section 0 instrumentation:** completion and outcome reporting, statistics, and logging
   what each arm received.
4. **Section 3.1:** the v0.1 vs v0.2 decomposition.
5. **Section 4.1:** oracle interventions, and section 6 baselines (retrieval).
6. **Section 5 coverage:** unanswerable, then the size sweep, then paraphrases, then the rest.
7. **Section 6a:** base vs fine-tuned 8B under native conditions (local lower-bit quant, or RunPod after the gate opens).
8. **RunPod:** the dispatcher/thinker pairing, after CJ's go.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
