# Task: make all 8 eval generators answerable and their scorers fair

`original/` holds 8 long-context eval-task generators (spec `BRIEF.md`). An independent audit
(`audit/REPORT.md`, read it fully) found:
- answer-key defects: **Cerebex** (key filters on hidden divisions; delegate contradiction; key 0
  on most seeds), **SELMA** (visible Date headers contradict event order; key mostly "Unassigned"),
  **TheDixieFlatline** (CORRECTION email never emitted; stray 'a' in a Date header);
- wording issues: **MasterControl** (question labels vs summary labels; what is summed),
  **Neuromancer** (increases worded as deductions);
- scorer unfairness in all tasks (sections 3 and "Suggested scorer fixes").

For each task write `fixed/<same name>.py` that:
1. fixes every answer-key/wording defect listed for it (see REPORT sections 2 and 3);
2. has a fair `score()`: 1.0 for a correct answer in any reasonable format (bare, sentence,
   markdown bold/italics, quotes, bullet list, JSON, trailing period, case changes, numbers with or
   without $ / thousands commas, extra explanation), and < 1.0 for wrong answers AND for hedged
   answers naming more than one candidate;
3. keeps the task idea, difficulty, grep-resistance, sizes (~60K/300K/1.2M), stdlib only,
   determinism across processes, valid Python 3.11 syntax (no backslashes inside f-string
   expressions). Where generation is unchanged (scorer-only tasks: Multivac, GLaDOS, SHODAN), keep
   generate() output byte-identical;
4. adds self-test asserts in `__main__` covering the fixed defect (seeds 0-9, all sizes) and the
   scorer formats/hedges (seeds 0-4).

Verify and iterate until ALL pass:
- `python3 check.py fixed/*.py`
- `python3 -I fixed/<f>.py` for each
- `python3 -I audit/scorer_battery.py fixed /tmp/battery.json` → zero flags (correct<1 or wrong/hedge>=1)
- the text-only solvers in `audit/` (e.g. part1_TheDixieFlatline_solve.py, part1_SELMA_orders.py,
  part1_SHODAN_solve.py, part1_Cerebex_trace.py) agree with the key on seeds 0-9 small (adapt their
  paths to `fixed/`; if a solver needs updating because the text format legitimately changed,
  update the copy in `audit/` and say so).
Never edit `original/`, `check.py`, `BRIEF.md`. Write `FIXES.md`: per task, defects, changes,
and the evidence each check now passes. Then stop.
