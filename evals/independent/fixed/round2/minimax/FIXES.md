# Fixes for the four eval-task generators

For each generator in `original/`, this document describes the defect that the
real evaluation found, the smallest change in `fixed/` that fixes it, and the
self-test assertions that prove the defect is gone for seeds 0–9 at every size.

All four fixed files pass `python3 check.py fixed/*.py`; the originals are
unchanged (and still pass the same harness).

---

## 1. `MasterControl.py`

### Defect

`score()` parsed natural-text answers with this regex:

```python
name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", re.IGNORECASE)
```

`re.IGNORECASE` is wrong here: the bracket-shaped character classes `[A-Z]`
already constrain what gets captured, but `IGNORECASE` lets the engine match
content past the second capitalized word. As soon as the right name appeared
in a longer sentence, the captured "name" grew to include everything until the
next lowercase turn. For example `"Priya Patel was the only employee flagged..."`
was matched as one giant "name" `Priya Patel was the only employee flagged`,
which never equals the truth name (`priya patel`); `name_ok` therefore became
`False` even when the right name was present, and `score()` returned 0.5
(amount right, name wrong) instead of 1.0.

### Change

Drop `re.IGNORECASE` from the name-pattern compilation. The truth-name
comparison itself stays case-insensitive (`.lower()` on both sides), which is
robust to formatting without paying the cost of breaking the regex.

```python
# fixed/MasterControl.py
name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
amount_pattern = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)")
```

### How the assertion proves it

`__main__` now sweeps seeds 0–9 × {small, medium, large} and, for each cell,
checks two cases:

1. A sentence with the **correct full name embedded** plus the **correct
   amount** scores **exactly 1.0**. This is the original bug shape — without
   the fix the regex over-matches the sentence and `name_ok` collapses.
2. A sentence with a **wrong name** but the **right amount** scores
   **strictly less than 1.0**. Guards the fix against regressing to "always
   accept" by removing the bracketed character class.

All 30 cells PASS, confirming the embedded-name case works while a wrong
name still fails.

---

## 2. `Multivac.py`

### Defect

`get_question()` and `get_answer()` were each calling `self.rng.choice(req_ids)`
independently inside `generate()`. Because `rng.choice` advances the RNG state,
the question named one requirement and the answer key described a *different*
one — 18/18 (seed × size) pairs the evaluation checked mismatched. A solver
who produced the "truth" structure from the answer key was answering a
question nobody had asked.

### Change

Add a `pick_target_requirement()` helper that selects the requirement once,
and pass that requirement into both `get_question()` and `get_answer()`.
`generate()` picks it once and threads it through.

```python
# fixed/Multivac.py
def pick_target_requirement(self):
    req_ids = list(self.current_state.keys())
    return self.rng.choice(req_ids)

def get_question(self, target_req):
    return f"What is the current status and full description of requirement {target_req}?"

def get_answer(self, target_req):
    req = self.current_state[target_req]
    return {"req_id": target_req, "status": req["status"],
            "description": req["description"]}

def generate(seed, size):
    ...
    target_req = gen.pick_target_requirement()
    return {
        "context": gen._generate_context(),
        "question": gen.get_question(target_req),
        "answer":   gen.get_answer(target_req),
        "meta":     gen.get_meta(),
    }
```

### How the assertion proves it

`__main__` parses `What is the current status and full description of requirement (R\d+)`
out of the returned question and compares it to `data["answer"]["req_id"]`.
The loop covers seeds 0–9 × {small, medium, large}. Every cell must satisfy
`asked == answered`. 30/30 PASS — the asked requirement is the one the answer
key describes.

---

## 3. `TheDixieFlatline.py`

### Defect

The final holder's location was the answer. An employee was assigned an
office exactly once, in the dictionary `person_to_loc` at the start of
generation. That string was written into the **context** only when that
specific employee happened to be chosen by a `move` or `failed_move` signal
event. If the final holder had never been picked for such an event (a frequent
outcome), there was no mention of their office anywhere in the thread — the
truth simply wasn't derivable from the document. The eval found this in 3 of
5 (seed × size) cells it sampled; a systematic run finds more.

### Change

Append a single "Office Seating Chart" email to `messages` *before* the main
message loop, listing every employee and their assigned office from
`person_to_loc`. The body is built in the same workplace-email prose the rest
of the thread uses, in the same chronological place (earliest message-ID,
earliest date). No RNG calls are made while building it, so the post-fix
state equals the pre-fix state from the perspective of every downstream
`rng` use — determinism is preserved exactly.

```python
# fixed/TheDixieFlatline.py  (just before the main message loop)
seating_lines = [f"- {n}: {person_to_loc[n]}" for n in names]
seating_body  = (
    "All,\n\nBelow is the current office seating chart for everyone on the team. "
    "Please confirm your listed office and direct any move requests to Facilities.\n\n"
    + "\n".join(seating_lines)
    + "\n\nThanks,\nFacilities"
)
messages.append(
    f"Message-ID: <000000@corp.local>\nDate: {timestamp}\n"
    f"From: Facilities\nTo: All\nSubject: Office Seating Chart\n\n{seating_body}"
)
```

`move` / `failed_move` events still override the directory entry whenever
they happen — so the directory is a baseline that later events can contradict.
The solver must still cross-reference "what does the directory say?" with
"is this the most recent move for this person?" the way they had to before;
the directory only plugs the gap for holders with no move events at all.

### How the assertion proves it

`__main__` sweeps seeds 0–9 × {small, medium, large}; for each cell it asserts
the truth (the final location string) is **literally contained in the
context**. Before the fix this fails for any final holder who never received a
move email. After the fix every cell's directory entry makes the holder's
office searchable text. 30/30 PASS.

---

## 4. `SELMA.py`

### Defect

The timeline can fire several ownership-clearing events: a `decline`, a
`cancel`, and a 10%-probability `unassign` side-effect at the end of each core
iteration. All three set `current_owner = None` in the truth computation, so
the ground-truth key becomes `"Unassigned"`.

In the email-generation loop, however:

* `unassign` had **no elif branch** at all and silently fell through to the
  generic `else: # note` branch, producing a "Note: AI Ethics Review Update"
  email whose body says "the AI Ethics Review is progressing well. The team
  is handling the current deliverables." — which never states the role is
  unassigned.
* `decline` produced "Update: Unable to Lead AI Ethics Review" with body
  "I need to decline leading … Please reassign this responsibility." — names
  nobody, doesn't say "unassigned", implies a forthcoming reassignment.
* `cancel` produced "Update: AI Ethics Review Postponed" with body
  "has been postponed indefinitely. No further action is required at this
  time." — also avoids saying "unassigned".

So the latest AI Ethics email in the thread could quietly disagree with the
key: the key said `Unassigned` while the latest email's signature or
declination text named a previous lead. 3 of 5 cells evaluated.

### Change

Three minimal edits to the existing if/elif chain (no new state, no new RNG
calls):

1. Add an explicit `elif etype == "unassign":` branch that produces a clear
   "the lead position is now unassigned" email in the same prose style.
2. Tighten the `decline` subject and body so the message itself says
   "Position Now Unassigned" and "the lead position is unassigned until a
   new lead can be confirmed".
3. Tighten the `cancel` subject and body similarly with "Position Now
   Unassigned" and "the lead position is now unassigned".

The `assign`, `reassign`, `correct`, `delegate`, and filler branches are
untouched, so any cell that previously had a named lead is unaffected.

```python
# fixed/SELMA.py  (excerpts)
elif etype == "decline":
    subject = "Update: AI Ethics Review Lead Declined -- Position Now Unassigned"
    body = ("...the previous AI Ethics Review lead has declined... "
            "the AI Ethics Review lead position is unassigned until a new "
            "lead can be confirmed...")
elif etype == "cancel":
    subject = "Update: AI Ethics Review Cancelled -- Position Now Unassigned"
    body = ("...has been cancelled and the lead position is now unassigned...")
elif etype == "unassign":
    subject = "Update: AI Ethics Review Lead Unassigned"
    body = ("...the AI Ethics Review lead position is now unassigned...")
```

### How the assertion proves it

`__main__` sweeps seeds 0–9 × {small, medium, large}; for each cell it
locates the **most recent AI Ethics email** (walking `"From: "` markers
backwards from the end of the context until one contains `"AI Ethics"`),
then asserts:

* If the truth is `"Unassigned"`, that email's lower-cased body must contain
  the substring `"unassigned"`.
* If the truth is a name, that email must contain the name verbatim.

That is exactly the contract that was broken before the fix. 30/30 PASS,
confirming the truth is now consistent with the most recent ownership email
in every required cell.
