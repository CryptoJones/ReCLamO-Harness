# Independent-eval audit: are the tests still broken?

Audited 2026-10-08 against main @ 458e2f7 (`evals/independent/fixed/active`). No repo changes,
no LLM or network calls. Generators were run locally with `python3 -I`.

For each answerability cell, the context was solved from the text alone and the answer written
down before the key was opened (see `part1_<Task>.md`). Only then was the key compared and the
generator traced.

**Short answer: yes.**
- Cerebex is broken on every seed.
- SELMA's key is ambiguous on about a third of seeds.
- TheDixieFlatline is unanswerable on about one seed in six.
- Several scorers (Multivac, SELMA, MasterControl, GLaDOS) give partial or zero credit to
  correct answers in ordinary formats, and real #22 re-run answers were marked down this way.
- Most scorers give full credit to answers that hedge between two candidates.
- SHODAN, GLaDOS and Neuromancer have sound keys.

## 1. Verdict table (answerability, small)

| Task | Seed 0 | Seed 1 | Notes |
|---|---|---|---|
| Cerebex | UNDERIVABLE (key 910; the text supports 3952) | UNDERIVABLE (key 0 matches only as the default) | Divisions are never stated, and the named delegate is secretly not in Operations. The key is 0 on 39/50 seeds. |
| SELMA | SOUND (Skyler Martin) | AMBIGUOUS (email order says Unassigned = key; Date headers say Jordan Miller) | Date headers are random within a year. Date order disagrees with the key on 68/200 seeds. The key is "Unassigned" on 141/200. |
| TheDixieFlatline | SOUND, hard but fair (Datacenter Beta) | SOUND, hard but fair (Room 111) | The CORRECTION email is never written out, so 34/200 small seeds are underivable (not seeds 0–4). |
| SHODAN | HARD-BUT-FAIR | HARD-BUT-FAIR | A text-only parser reproduces the key on seeds 0–4. |
| GLaDOS | SOUND | SOUND | Shortcut: the certifier is always the renamed Treasurer. |
| Neuromancer | SOUND | HARD-BUT-FAIR | Increases are worded as deductions, but the answer can still be derived from the "approved for $X" lines. |
| MasterControl (not blind-audited) | key defensible | key defensible | The question's labels don't match the audit summary's labels. |
| Multivac (not blind-audited) | answerable | answerable | The re-run answers match the key. |

## 2. Answerability defects

- **A1. Cerebex: the key filters on hidden data.** The truth counts only approvals by the
  Operations division (Cerebex.py 246–248). Divisions are assigned internally (99–107) and
  never appear in the text. The leave notice names a deputy for "all Operations expense
  approvals" (231–233), but that deputy is deliberately drawn from outside Operations (127–129,
  138), so their approvals are excluded even though the question says to include them.
  - Seed 0: the named delegate's $3,952 is excluded, and the key is 910.
  - Seed 1: the key is 0.
  - The RLM answered 3952 and 2809 in both runs, which are the readings the text supports.
  - The truth is 0 on 39/50 small seeds.
  - Suggested fix: add a staff directory with divisions, and count delegated approvals.
- **A2. SELMA: visible dates contradict event order.** The Date header shown on each email is
  random within the year (line 290), while the key follows email order (line 310). Sorting by
  date disagrees with the key on 34% of seeds. The key is "Unassigned" 70% of the time.
  - Suggested fix: print the real dates, and balance the final state.
- **A3. TheDixieFlatline: the CORRECTION email is never written out.** The guard
  `if action != "correction"` at line 170 skips it, so about 17% of seeds are unanswerable.
  First-run medium seed 1 is affected.
  - Suggested fix: drop the guard.
- **A4. Neuromancer: increases are worded as deductions** (`abs(adj)`, lines 121–126). The
  answer is still derivable.
- **A5. SHODAN: no key defect.** The task is brittle: only 1–4 of 18 shipments earn credit.
- **A6. MasterControl: the question's labels don't match the summary's labels** (80–90), and
  "flagged expenses" means all of the culprit's transactions without saying so.
- **A7. GLaDOS: a shortcut, not a defect.**

## 3. Scorer robustness

The battery made 1,701 probes over 8 tasks × seeds 0–4 at small size and raised 251 flags. Raw
results are in `scorer_battery.json`; the script is in `scripts/`.

### Correct answers scoring below 1

| Task | Correct answer | Score | Line |
|---|---|---|---|
| Multivac | `**Status:** On Hold` / "status is On Hold" / table / `Status - X` | 0.5 | 259–264 |
| SELMA | `**Name**` in a sentence, JSON, quoted name, "Name, who…", "Last, First" | 0.0 | 491 |
| SELMA (truth Unassigned) | "The answer is Unassigned." / "…is currently unassigned." | 0.0 | 477 |
| MasterControl | lowercase or uppercase name; "Patel, Priya" | 0.5 | 172 |
| GLaDOS | "Passed? Yes"; "DID pass" (a real re-run answer) | 0.8 | 1336 |
| GLaDOS | "$1.59 million" | 0.6 | 1349 |
| Cerebex | "$910 across … (3 claims)" (a number after the total) | 0.5 | 293 |
| SHODAN | "Alderwick office: 0" | 0.0 | 612–615 |
| TheDixieFlatline | a full-sentence answer | 0.5 | 219 |
| TheDixieFlatline | "Vault" for "The Vault" | 0.0 | 219 |

### Wrong or hedged answers scoring 1.0

- **Cerebex:** "1160 (not 910)".
- **GLaDOS:** "not approved".
- **MasterControl:** two names or two amounts.
- **Multivac:** a wrong status alongside the right one.
- **Neuromancer:** "Not $X; it is $truth".
- **SELMA:** two names.
- **TheDixieFlatline:** "A or B".

### Suggested scorer fixes (not applied)

- **Multivac:** search for the value within about 40 characters after "status".
- **SELMA:** strip punctuation per token, and accept "unassigned" phrasing.
- **MasterControl:** match the name case-insensitively.
- **GLaDOS:** accept yes / "did pass", and reject "not approved".
- **Cerebex:** take the number after "total".
- **SHODAN:** add "office" to the connector words.
- **TheDixieFlatline:** relax the 50-character penalty.
- **All:** reject answers that name two or more candidates.

## 4. #22 cells affected

| Cell | Run | Recorded | Verdict |
|---|---|---|---|
| Cerebex, all sizes, both modes | first and re-run | various | Invalid measurement |
| Multivac small s1, rlm and plain | re-run | 0.5 | Correct answers; should be 1.0 |
| GLaDOS small s1 rlm | re-run | 0.8 | Correct answer; should be 1.0 |
| SELMA small s1 (Jordan Miller), rlm and plain | both | 0 | A defensible date-order reading |
| SELMA medium s1 and large s0 | first | 0 | Likely the same |
| MasterControl small s0 plain | re-run | 1.0 | Lenient: the answer hedges to the key |
| TheDixieFlatline medium s1 | first | 0 | Unanswerable |
| SHODAN, Neuromancer, Dixie small, other GLaDOS | both | — | Valid; these misses are the models' own |

Plain-mode rows store only `content[:2000]` (`examples/bench.py:316`), so long plain answers
can't be re-scored from the rows.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
