# Independent eval tasks (Flatline Roundtable, non-Anthropic lanes)

These task generators were written by models that had nothing to do with building
ReCLamO-Harness. The harness, its prompt and its own tests were written by Claude models
(Opus orchestrating, Fable implementing). Those tests were also designed by the same
authors as the prompt, so they likely overstate what the harness can do (see
[#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22)).

To get tests we did not write, the brief in [`BRIEF.md`](BRIEF.md) went on 2026-10-07 to
the eight non-Anthropic lanes of CJ's Flatline Roundtable. They ran one lane at a time.
Each lane saw only the brief: no repo, no harness prompt, no other lane's answer. The CLI
lanes ran from an empty directory, which was still empty afterwards. One lane was
excluded. **Proteus** runs Qwen 3.7 Flash, the same model family as the system under
test, so its task could favour Qwen.

## What is here

| Path | Contents |
|---|---|
| `BRIEF.md` | The exact brief every lane received |
| `answers/<lane>.md` | Each lane's full response, verbatim (task description and code) |
| `generators/<lane>.py` | The Python block extracted from that response, **byte-for-byte unmodified** |
| `manifest.json` | Provenance (vendor, model, harness), sha256 of each generator, sizes, status |
| `validate.py` | The validator used: runs each generator's self-test and checks it in a no-network container |
| `validation-report.json` | Raw validator output (originals) |
| `check.py` | The same checks without Docker |
| `fixed/self/` | Each original author's own fix, with the request and response |
| `fixed/minimax/` | MiniMax-M3's fixes for all five, its task and `FIXES.md` |
| `fixed/active/` | **The evaluation set**: one passing version per task |

The generators are kept exactly as delivered, defects included. That is what makes them
independent. If we repair one, the repaired copy goes in a separate file with a diff and
a note, and the original stays here unchanged.

## Status

Each generator was validated in `python:3.12-slim` with `--network none`, as a non-root
user, on a read-only filesystem (`validate.py`). The checks are:

- its own `__main__` self-test passes;
- context sizes are about 60K, 300K and 1.2M characters;
- the same seed gives the same output, both within one process and across separate
  processes;
- a different seed changes the output;
- `score(truth) == 1` and `score("") < 1`.

`check.py` runs the same checks without Docker.

Five originals failed. They were **not** left broken. Each repair went the same way:

1. The failing generator went back to the lane that wrote it, together with the
   validator's exact findings. You can read the request and the response under
   `fixed/self/`.
2. In parallel, **MiniMax-M3**, a non-Anthropic model running in a sandboxed Claude Code
   session, repaired all five against `check.py`. Its work and reasoning are in
   `fixed/minimax/` and `FIXES.md`.
3. The active version is the author's own fix when that fix passed, which keeps
   authorship independent, and the MiniMax fix otherwise.

**`fixed/active/` is the evaluation set. All eight tasks pass.**

| Lane | Model | Task | Original | Active version |
|---|---|---|---|---|
| GLaDOS | xAI grok-4.6 | Transit co-op records: net authorized amount and certifying member for the current legal successor of a renamed project, under bylaws and SOP | pass | original |
| SHODAN | OpenAI gpt-6-astra | Month-end packet: per-office freight credits after signed corrections, custody findings and agreement terms | pass | original |
| TheDixieFlatline | Google gemini-3.1-pro-high | Chain of custody: final room of an asset through renames and transfers (medium size ≈260K) | pass | original |
| Cerebex | Z-AI glm-5.3-flash | Expense emails: travel total after amendments and reversals | self-test collided when truth = 0; f-string syntax invalid on Python 3.11 | **author's fix** + MiniMax 3.11 syntax patch (output byte-identical) |
| Neuromancer | DeepSeek v4-flash | March travel reimbursed after adjustments and denials | small size degenerate ($0); lenient scorer | **author's fix** |
| SELMA | NVIDIA Nemotron 3 Super | Final owner of a review after reassignments in an email thread | depended on `PYTHONHASHSEED` | **author's fix** |
| MasterControl | Mistral Medium 3.1 | Only employee flagged for two audit issues, plus their total | scorer regex split `39195` into `391`/`95` | **author's fix** |
| Multivac | Nous Hermes 4 405B | Requirement status after merges and splits | contexts 2.7K–16K; scorer missed dict form | **MiniMax fix** (author's second attempt overshot sizes and kept the scorer bug) |

Notes: Multivac's descriptions are templated, so its difficulty comes from following
requirement IDs through long merge chains rather than from paraphrase. Originals stay in
`generators/` byte-for-byte, and every file is pinned by sha256 in `manifest.json` and
checked in CI.

## Running

```sh
# Check the evaluation set (no Docker needed)
python3 evals/independent/check.py evals/independent/fixed/active/*.py

# Validate the originals in Docker (the directory must be one Docker Desktop can mount)
python3 evals/independent/validate.py evals/independent/answers ~/.cache/reclamo/rtgen

# Use a generator directly
python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('g', 'evals/independent/fixed/active/SHODAN.py')
g = importlib.util.module_from_spec(spec); sys.modules['g'] = g; spec.loader.exec_module(g)
d = g.generate(0, 'medium'); print(len(d['context']), d['question']); print(d['answer'])
"
```

Running these against the harness and the plain model is tracked in
[#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22). The prompt and defaults
are frozen before that run, with no tuning on these tasks.

```sh
# The frozen #22 run: rlm vs plain, resumable, one task x size per batch
uv run python evals/independent/run_eval.py --profile pluto --sizes small --out runs/independent.json
uv run python evals/independent/run_eval.py --profile pluto --sizes medium --resume runs/independent.json
uv run python evals/independent/run_eval.py --summary-only runs/independent.json
```

## Results

The frozen run (harness at `e17580f`, 80 rows, 2026-10-07) is written up in the main
README under
[Independent evaluation](../../README.md#independent-evaluation-tasks-written-by-other-models).
In short: below the model's window the plain model beat the harness. Above it, only the
harness can answer, and it was exact on 5/12 answerable medium cells and 1/6 large
ones. The run also found answer-key defects in three generators, which the files here
keep unchanged:

- Multivac: the key is for a different requirement than the one the question asks
  about.
- TheDixieFlatline: the starting offices are never stated, so some answers are not in
  the text.
- SELMA: a silent `unassign` event can make the key "Unassigned" when the last email
  names a lead.

It also found that MasterControl's scorer rejects a name that is written inside a
sentence.

## Round 2: defects found by the evaluation

The #22 run (PR #33) found defects that `check.py` could not catch, because it only checks
that a key scores itself:

- **Multivac:** the answer key described a different requirement than the question asked.
- **TheDixieFlatline:** the answer was sometimes impossible to derive, because starting
  offices were never stated.
- **SELMA:** an unassignment produced no email.
- **MasterControl:** the scorer rejected correct answers phrased as sentences, and it
  rejected unformatted amounts.

Each defect went back to its author lane first, and MiniMax-M3 repaired all four in
parallel. Every fix was then checked with `fixed/round2/verify_defects.py` over seeds
0–9 at every size, and with `check.py`.

| Task | Author's own fix | Active version |
|---|---|---|
| TheDixieFlatline | **pass** | author (Gemini) |
| SELMA | incomplete (2/30 cells still unexplained) | MiniMax |
| Multivac | failed its own new self-test | MiniMax |
| MasterControl | failed its own new self-test | MiniMax |

For MasterControl, the generated data is byte-identical to the previous version; only the
scorer changed. Everything is under `fixed/round2/`: requests, responses, both sets of
fixes and `FIXES.md`. The #22 numbers were measured on the earlier versions and have not
been re-run.

## Round 3: the independent audit (2026-10-08)

An auditor solved every task from the text alone before looking at any key, and ran 1,701
scorer probes (`audit/REPORT.md`). Both #22 runs had been scored with these versions. It
found:

- **Answer keys:**
  - Cerebex: the key filtered on divisions the text never stated.
  - SELMA: the visible dates contradicted the event order.
  - TheDixieFlatline: the CORRECTION email was never emitted.
- **Wording:** MasterControl and Neuromancer.
- **Scorers:** in all 8 tasks, correct answers in ordinary formats were marked down and
  hedged answers got full credit.

Same procedure as before: each author lane got its findings and MiniMax-M3 repaired all
eight in parallel. Only Neuromancer's author fix passed everything. TheDixieFlatline's
author fix looked clean but still dropped the CORRECTION email, which the text-only solver
caught. The other active versions are MiniMax's.

The active set was then verified with:
- `check.py`;
- each self-test;
- the audit's `scripts/scorer_battery.py` (0 flags, now run in CI by
  `tests/test_scorer_fairness.py`);
- the SELMA solver (date order = key on 100/100 seeds);
- a CORRECTION-count assertion for TheDixieFlatline;
- byte-identical generation for the scorer-only tasks.

Known residuals:
- SELMA's key is "Unassigned" on about 62% of seeds.
- Cerebex is 0 on about 26% of seeds, and some "paperwork" mentions are non-travel
  distractors.

## Round 3.1 (scorer-only, 2026-10-08)

Issue #63: Multivac's `score()` gave 0.2 to a correct
`R142: <description> — Status: Pending` answer. The description had to end at
punctuation or at the end of the text, so a dash, bullet, newline or markdown closer
followed by the status field failed that check. Three fixes, all inside `score()`:
- The description may now be followed by another field label (`Status`, `Priority`,
  `State`). A dash, bar or bullet before the label is allowed, and so is a
  `(Status: ...)` paren.
- A paragraph break ends the status field, so a later "the status was originally
  Pending" no longer counts as a hedge.
- The requirement id must match whole, so `R14` no longer matches `R142`.

**Contexts, questions and answer keys are unchanged.** `generate()` output is
byte-identical for every size and seeds 0-9, so the exam is still frozen. The scorer
battery gained probes for the `ID: value` shapes in all 8 tasks (2,111 probes, 0 flags).
The other seven scorers already handled these shapes and are untouched.

To re-score rows produced before this round:
`uv run python evals/independent/run_eval.py --rescore FILE [--out NEW]`. It writes
`FILE.rescored.json` plus a summary, and records `old_score` / `new_score` on every row.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
