# Task: repair four eval-task generators (answerability / scorer defects)

`original/` holds four long-context eval-task generators (spec: `BRIEF.md`). They pass
`python3 check.py original/*.py`, but a real evaluation found these defects:

1. **Multivac.py** — the answer key never matches the question: `get_question()` and
   `get_answer()` each call `rng.choice` separately, so the key describes a different
   requirement than the one asked about (mismatch in 18/18 seed×size checked). Pick the
   target requirement once per `generate()` and use it for both.
2. **TheDixieFlatline.py** — the answer is sometimes absent from the context: starting
   offices/locations are never written into the text, so when the final holder never moved
   or confirmed a location the answer can't be derived (3 of 5 cells). Make every fact the
   answer depends on appear in the context, in the task's prose style.
3. **SELMA.py** — a random `unassign` event changes the truth but produces no email, so the
   key says "Unassigned" while the latest email names a lead (3 of 5 cells). Every
   ownership-changing event must be visible in the thread.
4. **MasterControl.py** — `score()`'s name regex runs with IGNORECASE, so
   "Priya Patel was the only employee flagged..." matches as one long "name" and a correct
   answer gets 0.5. A correct full name embedded in a sentence must get full name credit;
   wrong names must still fail.

For each, write `fixed/<same name>.py`: smallest change that fixes the defect, same task
idea/difficulty, stdlib only, deterministic across processes, valid Python 3.11 syntax
(no backslashes inside f-string expressions). Add self-test assertions in each file's
`__main__` that PROVE the defect is gone for seeds 0–9 at every size (e.g. Multivac: the
asked requirement is the one the answer describes; Dixie: the true final location string
occurs in the context; SELMA: truth consistent with the last ownership email; MasterControl:
name-in-sentence + right amount scores 1.0, wrong name < 1). Then iterate until
`python3 check.py fixed/*.py` passes AND each `python3 fixed/<f>.py` self-test passes.
Never edit `original/`, `check.py` or `BRIEF.md`. Write `FIXES.md` describing each defect,
the change and how the new assertions prove it. Then stop.
