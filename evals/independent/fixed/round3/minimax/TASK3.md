# Follow-up: finish Cerebex.py

`fixed/Cerebex.py` fails its own `__main__` self-test (run `python3 -I fixed/Cerebex.py` to see
the AssertionError), and `audit/scorer_battery.py` still flags one case: the "show_work" correct
answer ("Qualifying: a + b = T. Total: T") scores 0.3. Fix both without weakening anything:
- every answer-key fix from TASK.md must still hold (divisions stated in the text, delegated
  approvals counted consistently with the question, truth non-zero on most seeds);
- a correct final total must score 1.0 even when other numbers appear earlier as working; a
  hedged answer naming a wrong total as THE answer must still score < 1.
Verify: `python3 check.py fixed/Cerebex.py`, `python3 -I fixed/Cerebex.py`,
`python3 -I audit/scorer_battery.py fixed /tmp/b.json` → zero flags. Don't touch other files. Stop.
