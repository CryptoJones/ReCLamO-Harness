# Follow-up: MasterControl.py scorer still rejects plain amounts

`fixed/MasterControl.py` `score()` uses `amount_pattern = r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"`,
which splits an unformatted amount: "The answer is Priya Patel; total 39195." matches "391"
and "95", so a fully correct answer scores 0.5. Fix ONLY the scorer so that, for the truth
('Priya Patel', 39195):
- "The answer is Priya Patel; total 39195."            -> 1.0
- "Priya Patel was the only employee flagged, $39,195." -> 1.0
- "Priya Patel, $39195.00"                              -> 1.0
- "Someone Else, $39,195"                               -> < 1.0
- "Priya Patel, $39,000"                                -> < 1.0
Add these as asserts (for several seeds' truths, not just one) to the `__main__` self-test.
Generation must stay byte-identical (do not touch generate()). Verify with
`python3 check.py fixed/MasterControl.py` and `python3 fixed/MasterControl.py`, then stop.
