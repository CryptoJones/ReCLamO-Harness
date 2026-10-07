# Task: repair five broken eval-task generators

`original/` holds five Python files, each a long-context eval-task generator written to the
spec in `BRIEF.md`. Each one currently FAILS validation. Run `python3 check.py original/*.py`
to see the exact failures.

For each file, write a repaired copy to `fixed/<same name>.py` so that
`python3 check.py fixed/*.py` reports PASS for all five.

Rules:
- Keep each author's task idea, domain, question style and overall design. Make the smallest
  changes that fix the defects (scaling generation up for size is fine where needed).
- Do not weaken the task: answers must stay grep-resistant and computed from the generator's own
  data; scorers must stay strict about substance (wrong numbers/names must score < 1) while
  tolerating formatting.
- Standard library only, deterministic from the seed (no hash()/set-order dependence, no time).
- Never edit anything in `original/` or `check.py`.
- When done, write `FIXES.md`: for each file, the defects found and exactly what you changed and why.
- Iterate until `python3 check.py fixed/*.py` passes, then stop.
