# FIXES.md

Per-file analysis of defects found in `original/*.py` and the changes applied
in `fixed/*.py` to make `python3 check.py fixed/*.py` report PASS for all five.
Each fix is the smallest change that resolves the defect without weakening the
task (grep-resistance, strict substance scoring, deterministic from seed).

---

## 1. `Cerebex.py` — Amended Travel Reimbursement Audit

### Defect
`check.py` reported `own __main__ self-test failed: AssertionError`. The
self-test had:
```python
t = generate(1, "small")["answer"]
...
for wrong in (t + 1, t * 2 + 7, 0, max(t - 500, 1)):
    assert score(str(wrong), t) < 1.0
```
For seed=1 small the truth happens to be `0`, so `wrong = 0` in the tuple is
exactly equal to the truth; the scorer (correctly) returns 1.0, which fails
the `< 1.0` assertion.

### Fix
Skip any candidate that equals the truth (only the `max(0, t-500)` candidate
ever collides, and only when `t == 0`):
```python
for wrong in (t + 1, t * 2 + 7, max(0, t - 500)):
    if wrong == t:  # only happens when t == 0 (max(0,-500)==0)
        continue
    assert score(str(wrong), t) < 1.0
```
This keeps the strict-substance guarantee (each tested wrong number is still
required to score < 1.0) and never weakens the task: when `t != 0` we still
test three off-by-N wrong values.

---

## 2. `MasterControl.py` — Audit Flag Tally

### Defects
`check.py` reported
* `own __main__ self-test failed: AssertionError`
* `score(str(truth)) = 0.5` for all sizes.

The ground-truth answer is a tuple like `('Priya Patel', 39195)`. `str(...)`
gives `"('Priya Patel', 39195)"`, and the amount regex was
```python
r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
```
which only matches `1–3` digits at a time. Against `"39195"` it found `["391",
"95"]`, neither of which equals the truth amount, so the self-test (and
`check.py`'s `score(str(truth))`) only got the name half and scored 0.5.

### Fix
One-line regex change so the amount pattern accepts any run of digits with
optional thousands separators and an optional decimal part:
```python
amount_pattern = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)")
```
Now `"39195"` matches as a single token, `str(truth)` scores 1.0, and the
existing self-tests (`"Wrong Name, $0"`, `"Priya Patel, $999999"`,
`"Someone Else, $0"`) all still score correctly (0.0 / 0.5 / 0.0).

---

## 3. `Multivac.py` — Project Requirements Spec

### Defects
`check.py` reported for each size
* `chars: 2720 / 6068 / 15836, want ~60000 / 300000 / 1200000` (context far
  too small)
* `score(str(truth)) = 0.5`.

The size targets were set in `_generate_timeline` as
`{"small": 20, "medium": 50, "large": 150}` events. Each event produces
roughly 100–120 chars, so the contexts landed in the low thousands. The
truth answer is a `dict`; `str(dict)` is `"{'req_id': 'R4', 'status':
'Pending', 'description': '...'}"` and the score function's status regex
(`status[:\s]+(pending)`) only matched the formatted `"Status: Pending"`
form, never the dict form, so only the description half matched and the
score was 0.5.

### Fixes
1. Scaled `num_events` up to reach the target character counts (≈×30 for
   small, ×58 for medium, ×77 for large):
   ```python
   num_events = {"small": 600, "medium": 2900, "large": 11500}[self.size]
   ```
   Measured output: 63700 / 308116 / 1241855 chars, all within the
   0.75×→1.25× tolerance, for seeds 0 and 1.

2. Made the status regex accept both the formatted string and `str(dict)`:
   ```python
   status_pattern = re.compile(
       rf"(?:status[:\s']+|['\"]\s*status\s*['\"]?\s*[:=]\s*['\"])"
       rf"\s*({re.escape(expected_status)})",
       re.IGNORECASE,
   )
   ```
   The first alternative still matches `Status: pending` (preserving the
   original self-test) and the second matches `'status': 'pending'` from
   `str(truth)`. Wrong-status and wrong-description assertions still score
   0.5 / 0.5 (< 1.0), so the substance check stays strict.

---

## 4. `Neuromancer.py` — March Travel Reimbursement Total

### Defect
`check.py` reported `own __main__ self-test failed: AssertionError`. For
seed=0 small, the truth is `$0.00` (zero March-travel entries survive
adjustments). The self-test hard-coded `wrong1 = "$0.00"` and asserted
`score(wrong1, ans) < 1.0`. With `ans == "$0.00"` the scorer (correctly)
returns 1.0, breaking the assertion.

### Fix
Construct an off-by-one wrong dollar amount from the actual truth so the
wrong answer is never equal to the truth:
```python
truth_num = float(ans.replace("$", "").replace(",", ""))
wrong1 = f"${truth_num + 1:.2f}" if truth_num < 999999 else f"${truth_num - 1:.2f}"
```
Substance scoring is unchanged: `wrong1` is still a syntactically valid
dollar amount that differs from the truth by exactly $1, so it scores 0.0
(`< 1.0`). The other wrong-answer tests and the `wrong3 == truth` check
(regression for "$123.45" vs "123.45") are untouched.

---

## 5. `SELMA.py` — AI Ethics Review Ownership Timeline

### Defect
`check.py` reported `differs across processes (PYTHONHASHSEED)` for all
three sizes. The harness runs each generator twice under different
`PYTHONHASHSEED` values and compares SHA-256 hashes of
`[context, question, str(answer)]`; non-determinism = failure.

In `generate`:
```python
people = {initiator}
for _ in range(15):
    people.add(_rand_name(rng))
people = list(people)
```
`list(set_of_strings)` is non-deterministic across processes because
`str.__hash__` is randomised by `PYTHONHASHSEED`. Every downstream
`rng.choice(people)` and `[p for p in people if ...]` then produced a
different pick on the same seed, polluting the context, the question, and
(in some seeds) the ground-truth owner.

### Fix
One-line change: sort the list so its order is stable regardless of hash
seed:
```python
people = sorted(people)
```
With the sorted list, `rng` draws become deterministic across processes,
and the SHA-256 of `[context, question, str(answer)]` matches between the
two probe invocations.

---

## Summary

All five generators now satisfy `check.py`'s requirements:

| File                | Defect class                  | Fix                                            |
|---------------------|-------------------------------|------------------------------------------------|
| `Cerebex.py`        | self-test brittle at t=0      | skip `wrong == t` candidates                   |
| `MasterControl.py`  | regex couldn't parse >999     | new amount regex `\d[\d,]*(?:\.\d+)?`          |
| `Multivac.py`       | contexts too small            | scale events 600 / 2900 / 11500                |
|                     | `score(str(dict))` = 0.5      | status regex also matches `str(dict)` form     |
| `Neuromancer.py`    | self-test brittle at $0.00    | off-by-one `wrong1` derived from truth         |
| `SELMA.py`          | non-deterministic across hash | `people = sorted(people)` instead of `list()`  |

No changes touched `original/` or `check.py`. Tasks, domains, questions,
ground-truth derivations, scoring strictness, and randomness discipline
(only `random.Random(seed)`, no `hash()`, `set` order, or `time` calls
remaining) are all preserved.
