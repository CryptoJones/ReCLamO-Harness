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

## 1. Sample size and question sets

- **Main grid:** 8 tasks × 8 seeds (2–9) = 64 questions per arm per size, at small, medium and
  large. Target for later phases: ≥ 64 per cell. Grow toward 1,024 per cell once faster
  readers exist (RunPod).
- **Repeat runs:** 16 questions run 3 times each, same seed and arm, to measure run-to-run
  noise. Report the per-arm disagreement rate.
- **Paraphrases:** 3–4 rewordings of each question (formal, casual, indirect, messy), written
  by a model that is not under test. The key stays the same. Measure answer consistency
  across wordings.

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
7. **RunPod:** the dispatcher/thinker pairing and paper-faithful 8B, after CJ's go.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
