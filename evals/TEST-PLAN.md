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

## 1a. Pre-registered hypotheses for the main grid (frozen 2026-10-09 12:35 CDT)

Frozen before any seed 4–9 result was examined. Those runs started at 10:37 that day. Up to the
freeze, only row counts were read, never scores. Every hypothesis below is judged against this
text. Any change after the freeze is dated and labelled post hoc.

**Grid (sampling: Qwen3 presets).** CJ, 2026-10-09 12:30: run the full grid at the current
settings first, unchanged, as a comparison point, then repeat it with the model's own sampling
(#69). The grid is:
- 8 tasks × seeds 2–9 at small and medium on the four arms plain-32K, plain-128K,
  harness v0.1 32K and harness v0.2 128K. Plain-32K runs small only, because no medium question
  fits. Harness v0.2 32K ran on seeds 2–3 only, as a pilot;
- 64 large questions on harness v0.1 and harness v0.2 128K.

The grid then extends in rolling batches toward 320 pairs (section 1).

- **H1 (primary, one per size).** At small and at medium, harness v0.1 and plain-128K differ in
  exact-match accuracy on paired questions.
  - Test: two-sided exact McNemar.
  - Looks: at ≈ 107, 213 and 320 pairs, with **O'Brien–Fleming boundaries** (|z| > 3.0, 2.0,
    1.96).
  - This replaces the "Bonferroni or O'Brien–Fleming" choice in section 1. The decision is Dix's
    recommendation and can be overridden only before the first look.
  - At seeds 2–9 (64 pairs) no look is reached. That grid is reported as an estimate with
    confidence intervals and no test of H1.
- **H2 (secondary).** Harness v0.2 128K and harness v0.1 differ in exact-match accuracy at small
  and at medium (two-sided exact McNemar, unadjusted, labelled secondary).
- **H3 (secondary, delegation).** Harness v0.2 makes more `llm_query` sub-calls per question than
  v0.1 (one-sided paired Wilcoxon signed-rank, per question).
- **H4 (estimate, not a test).** At large size, where no plain arm fits, report completion rate
  and exact-match accuracy with 95% intervals for both harness arms.
- **H5 (secondary, sampling; #69).** For each arm, accuracy with the model's embedded sampling
  (temp 1.0 / top_p 0.95 / top_k 20) differs from the Qwen3 presets on the same questions
  (two-sided exact McNemar per arm, secondary). It also tests whether the H1 and H2 directions
  hold under both samplings. The native-sampling grid goes to separate files and is never pooled
  with the preset grid.

Provider and transport errors are `not_run` and are excluded pairwise, not scored 0 (#56).

**Scoring clarification (CJ, 2026-10-09 23:21, after the freeze but before any score was examined).**
- A request that Strata rejects with HTTP 400 `malformed tool call` is a **model failure, not a provider error**: the model wrote tool-call-shaped text instead of a code fence (#72).
- Such a row scores **0**, with failure type `malformed_tool_call`.
- Every analysis that contains such rows is also reported with them excluded, as a sensitivity check.
- As of seed 5: two rows, both harness v0.2 128K, Multivac, small (seeds 4 and 5).

## 1b. Amendment to the main-grid plan (2026-10-10 01:45 CDT; epic #80)

Dated and appended; section 1a is not rewritten. Written before any interim look and before any
seed 4–9 score was examined (only row counts and error rows have been read). Decisions from CJ
on 2026-10-10 ("Lets add all four to the plan"), after a 10-lane roundtable review.

**Correction: the H1 stopping boundaries.**
- Section 1a gave "O'Brien–Fleming boundaries (|z| > 3.0, 2.0, 1.96)". Those are **not**
  O'Brien–Fleming. By simulation (4M draws, 3 equally spaced looks), that rule rejects a true
  null 7.4% of the time, not 5%.
- **Corrected rule:** O'Brien–Fleming for K = 3 equally spaced looks, two-sided α = .05:
  **|z| > 3.471, 2.454, 2.004** at 1/3, 2/3 and all of the confirmatory pairs (c = 2.004 ×
  √(3/k)).
- z is computed from the discordant pairs as (b − c)/√(b + c). The exact McNemar p-value is
  reported alongside it at every look.

**Confirmatory set.**
- Seeds 2–3 were seen before the H1–H5 freeze, so they are **exploratory** and are never part of
  a confirmatory test.
- **Confirmatory = seeds 4 onward.** H1's 320 confirmatory pairs per size are seeds 4–43
  (8 tasks × 40 seeds).
- The looks fall after seed 17 (112 pairs), seed 30 (216) and seed 43 (320). If a look crosses a
  boundary, H1 stops for that size and the look is recorded here.

**H1 is run to 320 pairs** (#82) on its two arms only: harness v0.1 32K and plain-128K, at small
and medium, seeds 10–43, from the pinned code d816814.

**Multiplicity.**
- H1-small and H1-medium are two separate primary questions, one per input size, each tested at
  its own α = .05 with the boundaries above. No claim combines them.
- Holm-adjusted p-values across the pair are reported as a sensitivity check.
- H2–H7 are secondary and labelled so.

**H2 renamed.** H2 is a **configuration comparison** (v0.2 128K vs v0.1 32K). It changes prompt,
limits and window together, so it cannot attribute a difference to delegation.

**New secondary hypotheses** (paired, seeds 4–9, small/medium/large; estimates with
task-clustered 95% CIs, exact McNemar labelled secondary):
- **H6 (map-reduce, #84):** fixed-chunk map-reduce (same model as reader, deterministic prompts,
  one aggregation call) differs from harness v0.1 in exact-match accuracy. At large size this is
  the harness's only comparator.
- **H7 (REPL-only, #83):** harness v0.1 with `llm_query` disabled and not advertised differs from
  harness v0.1. A REPL-only score close to the harness score would mean the gain comes from code
  in a REPL, not from recursion.
- Both arms run from a separate checkout at a newer commit, recorded per row. The harness core is
  unchanged.

**Analysis specification** (#85; built on fixtures and not run on confirmatory data before the
first look):
- **Clustering:** with 8 tasks, the task is a cluster.
  - Alongside McNemar, report a task-clustered paired bootstrap CI (resample tasks, then
    questions) and a GLMM (logit, arm fixed effect, task random intercept).
  - Report leave-one-task-out estimates and the minimum detectable effect at each n.
- **Breakdowns:** per task, per generator author, and by evidence position (where the deciding
  fact and its correction sit).
- **Noise floor (A/A):** at small, plain-32K and plain-128K see identical input. Their
  discordance rate is reported as an A/A noise floor.
- **Cost and latency** are central results: per-arm seconds (p50/p95), prompt and completion
  tokens, sub-calls and turns.
- **Failure taxonomy:** answered, forced finish, turn cap, time limit, error limit, context
  overflow, `malformed_tool_call`, `not_run`.

**Construct-validity check (#86).**
- Per generator, a deterministic non-LLM shortcut solver (e.g. last-mentioned candidate, most
  frequent candidate, regex on the question's key terms), written blind to the answer keys.
- It is scored on seeds 4–9. Any generator where it scores high is reported as measuring search,
  not multi-hop reasoning.

**Framing (CJ, 2026-10-10: arXiv only).** The paper is a **transfer study**: one model, one serving
stack, these tasks. Only the LongBench Pro reproduction (#74) is called a replication.

## 1c. H1 interim looks: recorded 2026-10-16 03:50 CDT (H1 stopped for both sizes)

Dated and appended; sections 1a and 1b are not rewritten. Computed from `runs/exp-v02/h-v01-32k.json`
(harness v0.1 32K) and `runs/exp-v02/plain-131k.json` (plain-128K), pinned code d816814, 0 error rows
in either file, with `exact()` (score ≥ 1.0) and `mcnemar_exact()` from `paper/analysis/make_tables.py`.
Pairs are matched on (task, size, seed), confirmatory seeds 4 onward, 8 tasks per seed. b = harness
exact and plain not; c = plain exact and harness not; z = (b − c)/√(b + c); positive z favours the
harness. Boundaries from section 1b: |z| > 3.471 (112 pairs), 2.454 (216), 2.004 (320).

| Look | Size | n | Harness exact | Plain exact | b | c | z | Exact McNemar p | Boundary | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| seed 17 | small | 112 | 65 | 49 | 32 | 16 | +2.309 | .0293 | 3.471 | inside: continue |
| seed 17 | medium | 112 | 51 | 32 | 24 | 5 | +3.528 | .0005 | 3.471 | **crosses: stop** |
| seed 30 | small | 216 | 125 | 94 | 60 | 29 | +3.286 | .0013 | 2.454 | **crosses: stop** |
| seed 30 | medium | 216 | 104 | 68 | 49 | 13 | +4.572 | < .0001 | 2.454 | crosses (supplementary; see deviation) |

**Protocol deviation.** The seed-17 look was due when seed 17 finished (2026-10-15 ~00:00 CDT) and
was not performed; the grid ran on to seed 30 before any look was computed (2026-10-16 03:45 CDT,
during a pluto pause). Nobody read a score in between: only row counts and error rows were examined.
Consequences, applied as the pre-registered rule says:

- **H1-medium stopped at the first look** (112 pairs, z = +3.528 > 3.471, p = .0005). That is its
  confirmatory result. The medium rows for seeds 18–30 were collected after the stopping point; they
  are reported as a supplementary estimate (the seed-30 row above), never as the confirmatory test.
- **H1-small stopped at the second look** (216 pairs, z = +3.286 > 2.454, p = .0013), as planned.
- Holm across the two primaries: both adjusted p-values are below .05.
- The grid was stopped mid seed 31 (3 plain-128K and 2 harness small rows exist for seed 31). Those
  rows and any later seeds are not part of H1. Seeds 31–43 are **not run** for H1; if they are run
  later, it is for estimation only and is recorded here first.
- The task-clustered bootstrap, GLMM and leave-one-task-out analyses (#85) are reported at each
  size's stopping look.

## 1d. Amendment: scorer defect, final-statement scoring, and the status of H1 (2026-10-19; epic #80, issues #95, #97)

Dated and appended; sections 1a–1c are not rewritten. Decisions from CJ on 2026-10-19 (epic #80,
decisions 8–14), after a 10-lane Flatline Roundtable round 2. Written **before** any row was
rescored for a paper result; the diagnostic numbers below are labelled as such and are not results.

**The defect (#95).** The active round-3 scorers (`evals/independent/fixed/active/`, sha256-pinned
in `manifest.json`) contain "hedge" rules that mark an answer down for *showing its work*: several
dollar amounts anywhere in the text (MasterControl, GLaDOS), a "not"/"or" anywhere next to a second
number (Neuromancer), "not" followed by any word (SELMA), a status history before the final status
(Multivac), an office named more than once (SHODAN). The plain-128K arm shows its work; the harness
arm answers `Name; $X`. The penalty is therefore one-directional. Found on 2026-10-19 while
answering the roundtable's check for the MasterControl 0/27 plain cell: all 54 plain MasterControl
rows name the right employee and state the right total and score 0.3; 22 of 41 plain Neuromancer
zeros end with the right amount written in LaTeX (`\$27{,}039.83`), which the regex cannot read.

**Diagnostic only, not a result.** A one-off format-tolerant rescoring applied identically to both
arms (not a validated scorer) gives small: harness 127, plain 142 exact, b = 16, c = 31, z = −2.19;
medium: 104 vs 102, b = 19, c = 17, z = +0.33. Neither crosses the section-1b boundaries. The
recorded H1 (section 1c) therefore **cannot be reported as a result**.

**Status of H1.** The recorded stops in section 1c stand as the record of what the pre-registered
procedure did under the round-3 scorers. They are reported in the paper next to the recomputed H1,
with this deviation disclosed. **The recomputed H1 is not the pre-registered test**: its scorer was
chosen after the data were seen. It is reported as a corrected estimate with the same pairing, looks
and boundaries applied for comparability, and labelled as post hoc. #82 stays open; seeds 31–43 are
not run until the recomputed looks say whether the stop still holds.

**Human check first (#90).** CJ marks every confirmatory pair (432: seeds 4–30, small and medium,
both arms, arms blinded as A/B, the grader's score revealed only after both marks) on a side-by-side
sheet. Agreement with the round-3 grader and with the round-4 grader is reported per task and arm,
every disagreement listed. A key error found there is fixed or dropped for all arms at once and
logged here.

**The round-4 rule (what the corrected scorers do; `evals/independent/fixed/round4/`).** A scorer
grades the answer's **final statement**, with the same code for both arms:
1. Normalise formatting first: LaTeX money and `\boxed{}`, markdown emphasis, code spans, table
   pipes.
2. The final segment is the text from the last answer-marker line ("Final answer", "Answer",
   "Conclusion", "Total", "Therefore", ...) to the end; without a marker, the last paragraph. If the
   segment holds no candidate of the kind needed (a name when the total line carries only the
   amount), the whole text is searched for that component.
3. A hedge is an explicit alternative inside the final segment ("X or Y", "either", "possibly",
   "cannot determine") with at least two distinct candidates there. Other numbers or names in the
   working are not a hedge.
4. A candidate negated within about 20 characters before it ("not $X", "instead of $X") is skipped.
5. A wrong final answer scores as before. Only the verbosity penalty is removed.

Per task, as drafted (`fixed/round4/`, each self-contained): **MasterControl** takes the last
clean amount of the final segment (operands of a shown sum and parenthetical asides are skipped)
and requires the key's name among the names the final segment mentions, else anywhere;
**Neuromancer** takes the last clean amount of the final segment, equality within half a cent;
**SELMA** scores 0 when the final segment names people and none is the key, and "Unassigned" is a
competing candidate; **TheDixieFlatline** drops the "moved from/to" hedge (the destination is the
answer) and scores 0 when the final segment names a different location; **Multivac** reads the
*last* status label that is not a history or transition source ("from X to", "originally X"),
and lets a line break bound the description; **GLaDOS** takes amounts (≥ 10,000, so dates and
tallies do not count), the outcome and the name from the final segment first, requires a single
mention of the full name, and scores 0 when the answer was cut off mid-sentence; **SHODAN** uses
the final segment's or the last clean observation per office and gets a real per-label hedge
("Alderwick: 0 or 3"); **Cerebex** keeps its authoritative-figure logic on the normalised text and
follows "+ … = T" chains to the result. "Or"/"either" count as a hedge only between two candidates
in one clause; uncertainty words ("possibly", "cannot determine") count near a candidate. Candidate
names are drawn from each generator's own name pools, so "Final Audit Summary" is not a person.
Partial scores keep their round-3 values (0.2/0.3/0.4/0.5) and still count as not exact.

**One battery exception, declared here.** The audit battery's `previous_location_too` probe
("It moved from Room 101 to <key>") expects a score below 1.0. Under round 4 it scores 1.0 by
design: the final statement names the key as the destination, and the harness arm never writes
this shape, so the round-3 penalty was one-directional. `tests/test_scorer_fairness.py` allows
exactly this probe for TheDixieFlatline in `fixed/round4/` and nothing else. The other 2,106
probes raise zero flags.

**Diagnostic recount under the drafts (not a result; the hand-check and CJ's approval come first).**
Confirmatory pairs, seeds 4–30: small, harness 134 vs plain 148 exact, b = 16, c = 30,
z = −2.06; medium, harness 117 vs plain 103, b = 22, c = 8, z = +2.56 at 216 pairs, and
b = 11, c = 2, z = +2.50 at the seed-17 look (112 pairs) where H1-medium actually stopped
(boundary 3.471). Flips relative to round 3: 111 rows up, 0 down, each read by hand (MasterControl
54 plain + 7 harness; Neuromancer 22 plain; Multivac 3 plain + 7 harness; SELMA 8 plain; GLaDOS 8
harness; Cerebex 2 plain; SHODAN and TheDixieFlatline none). Under the drafts the small result
reverses and the medium result no longer crosses its confirmatory boundary.

**Validation before any paper number.** Each round-4 scorer must (a) pass its own self-test and
`check.py`; (b) raise zero flags on the audit's scorer battery (now run in CI for `round4/` as well
as `active/`); (c) reproduce every stored answer key byte for byte (generate() unchanged); (d) be
hand-read on every row whose exactness it flips relative to round 3, with the verdicts recorded on
#95; (e) agree with CJ's #90 marks at least as well as round 3 does on every task. A task where (e)
fails is reported under round 3 and round 4 both, and the disagreement is listed.

**Rescoring.** Rescoring writes new files (`runs/exp-v02/rescored-round4/*.json`, with `old_score`
and `new_score` per row and the round-4 sha256 set in `meta`), never over the recorded ones.
`manifest.json` gains a `round4` entry per lane; `active` is switched to round 4 only by CJ's merge
of the review PR, and every future run records which set scored it. Rows whose plain answer was
stored truncated at 2,000 characters (57 of 435 confirmatory plain rows; 55 of them `length` rows
with no final statement) are rescored on the stored text and flagged `rescore_truncated`.

**Reporting the unfinished rows (decision 9; #85).** The pre-registered primary stands: every pair
counts and an arm with no answer is wrong. Excluding pairs where plain's prompt `does_not_fit` is a
labelled **secondary** (decided before either arm ran). Excluding plain `length` rows, harness
`max_iterations`/`timeout` rows, and "both arms finished" are **sensitivity only** (the arm caused
the exclusion; no inference). Completion rate is reported per arm. The headline is task-conditional:
the per-task table and leave-one-task-out estimates are reported with every H1 number.

**Engine (decision 8; #97).** Every remaining paper run stays on the stack recorded in
`runs/replay/stackA-provenance.json` (Strata a4b679b1, `strata-flashnext.json`, huihui Flash-Next
UD-Q4_K_XL). Before any engine change a temperature-0 replay set (seeds 4–6, 8 tasks, small and
medium, 144 requests: plain, harness root turn 1, one sub-call shape) is captured twice on this
stack; the A-vs-A agreement is the engine noise floor any other build is judged against. Rows from
two engines are never pooled. Baselines (#83, #84) and #69 wait until the round-4 scorers are
approved.

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

  Decision (CJ, 2026-10-09 12:30): no mid-grid ablation. The full grid finishes on the presets.
  Then the same grid is repeated with the model's own defaults (#69, H5 in section 1a). Report
  which settings each published number used.
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

1. **Running now:** the main grid on seeds 4–9 (small, medium), then 64 large questions, all on
   the Qwen3 presets.
2. **Next:** the same grid with qwen4exp's own sampling (#69).
3. **Section 2:** validity checks.
4. **Section 0 instrumentation:** completion and outcome reporting, statistics, and logging
   what each arm received.
5. **Section 3.1:** the v0.1 vs v0.2 decomposition.
6. **Section 4.1:** oracle interventions, and section 6 baselines (retrieval).
7. **Section 5 coverage:** unanswerable, then the size sweep, then paraphrases, then the rest.
8. **Section 6a:** base vs fine-tuned 8B under native conditions (local lower-bit quant, or RunPod after the gate opens).
9. **RunPod:** the dispatcher/thinker pairing, after CJ's go.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
