# Part 1 — Cerebex answerability audit (small, seeds 0 and 1)

Written BEFORE opening the key or the generator source. Reading done with
`scripts/part1_Cerebex_filter.py`-style filtering (split on `\n\n\nFrom:`, drop the
noise subjects: Printer/badge, parking, Team lunch, Merged: agenda, Standup notes,
Flights to X "just research").

## What the text does and does not contain (both seeds)

- **No division membership for anyone.** `grep -i` for operations / engineering /
  finance / sales / department / division / reports to finds only "Please cc finance"
  and one line: the leave notice. Nobody is ever stated to be in the Operations
  division. Nobody's manager is ever stated; the only proxy is the `To:` of the
  request email.
- **One delegation notice per seed**, with no end date:
  - s0: `From: Zane Mbeki / To: Liam Mbeki / Date: August 1, 2024 / Subject: Approvals while I am on leave` — "While I am away all Operations expense approvals go through Liam — sign in my name and cc me."
  - s1: `From: Sam Marino / To: Yara Ito / Date: July 1, 2024` — "While I am away all Operations expense approvals go through Yara — sign in my name and cc me."
  This implies Zane / Sam are Operations managers and Liam / Yara are their delegates,
  but no request is ever addressed to Zane or Sam.
- **Dates are non-chronological within threads.** Approvals often predate the request
  (s0 Perth: requested Dec 6, 2024, approved Feb 7, 2024; s0 Riga correction dated
  Mar 9, 2024 but approval Aug 8, 2024; s1 Nairobi requested Oct 13, approved Jan 14).
  So "later message governs" cannot be resolved by date; only by document order.
- **Amendments sent from the wrong person.** e.g. s0 `From: Carla Marino` (the
  requester) "the decision is now declined" on her own Oslo invoice; s0 `From: Nina Cruz`
  (requester) "we are rescinding the approval" on her own training batch that was never
  approved; s1 `From: Uma Alvarez To: Viktor Haddad` amends the Yara Okafor meals batch.
- **"Decision on the two outstanding requests" emails reference paperwork that has no
  request email** (s0: "Yara's Tampere paperwork", "Yara's Seville paperwork"; s1:
  "Wen's Hanoi paperwork", "Yara's Hanoi paperwork", "Liam's Lyon paperwork"). Where the
  decision says "approve X at the submitted amount" and X has no request email, the
  amount is not in the text.

## Seed 0 — my answer: **3952** (low confidence; see UNDERIVABLE note)

Travel requests found (category = "<City> trip for ..."):

| Trip | Requester → To | Thread | Final status by doc order | Amount |
|---|---|---|---|---|
| Austin | Priya Cruz → Ben Kowalski | "Approved at $704.00"; Ben: "Correction ... real total came to $910.00 ... disregard my earlier email"; later decision email (Ben, Dec 7): "Between Yara's Seville paperwork and Priya's Austin paperwork, approve the latter at the submitted amount." | approved | $910 (or $704 by "submitted amount" — conflicting) |
| Perth | Yara Marino → Elena Chen | "Approved at $3,974.00"; Elena decision: "Between Yara's Perth paperwork and Yara's Tampere paperwork, approve the former" | approved | $3,974 |
| Oslo | Carla Marino → Elena Chen | "Not approved this cycle"; then "decision is now declined", $4,017 | declined | – |
| Hanoi | Carla Alvarez → Liam Mbeki | Jul 7 request; Liam Sep 7: "Approved at $3,952.00" | approved | $3,952 |
| Riga | Wen Chen → Elena Chen | "Approved at $3,192.00"; "Correction on the Riga invoice from Wen: the real total came to $1,122.00" | approved | $1,122 |

Operations filter: the only person textually tied to Operations approvals is Liam
(delegate for Zane's Operations approvals from Aug 1, 2024). Hanoi was approved by
Liam on Sep 7, 2024, inside the open-ended leave window. Ben Kowalski's and Elena
Chen's divisions are never stated. So the only defensible text-based answer is
**3952**; if the generator privately puts Elena or Ben in Operations, the answer is
not derivable from the text.

## Seed 1 — my answer: **0** (low confidence; see UNDERIVABLE note)

Travel requests found:

| Trip | Requester → To | Thread | Final status | Amount |
|---|---|---|---|---|
| Perth | Yara Ito → Nadia Weber | "Approved at $2,809.00" | approved | $2,809 |
| Nairobi | Jonas Devi → Zane Okafor | "Approved at $842.00"; Zane: "final amount is $689.00 ... decision is now declined"; Leo decision "Between Wen's Hanoi paperwork and Jonas's Nairobi paperwork, approve the former" (Nairobi not chosen) | declined | – |
| Hanoi (Wen) | no request email | Leo Novak: approve "Wen's Hanoi paperwork" "at the submitted amount" | approved? | amount absent |
| Hanoi (Yara) | no request email | Nadia Weber: "Between Liam's Lyon paperwork and Yara's Hanoi paperwork, approve the latter at the submitted amount." | approved? | amount absent |

Operations filter: the Operations delegate is Yara (Ito — the notice is addressed to
Yara Ito). No travel request is addressed to Yara Ito, and no request is addressed to
Sam Marino. Nadia Weber, Leo Novak and Zane Okafor have no stated division. On the
text alone the Operations-approved travel total is **0**. If any Hanoi paperwork is
meant to count, its dollar amount is not in the text, so the answer would be
UNDERIVABLE.

## Pre-key verdict

Both seeds look UNDERIVABLE as written: the question filters on "approver belongs to
the Operations division", and the context never states any person's division. Both
answers above rest on the assumption that the delegate named in the Operations leave
notice is the only identifiable Operations approver.

---

## Comparison with the key (opened after the section above was written)

| Seed | My text-only answer | Key | Match |
|---|---|---|---|
| 0 | 3952 (Liam's delegated Hanoi) | **910** | no |
| 1 | 0 | **0** | yes (by default, not by derivation) |

Generator internals captured with `scripts/part1_Cerebex_trace.py` (profile hook on
`generate`, no repo edits); raw output in `part1_Cerebex_trace_small.json`.

- s0: Operations managers are **Zane Mbeki and Ben Kowalski**. Key 910 = Priya Cruz's
  Austin trip, approver Ben Kowalski (Operations), corrected $704 -> $910. The deputy
  Liam Mbeki is **Marketing**, so the delegated Hanoi trip ($3,952) is excluded.
  Nothing in the text says Ben Kowalski is in Operations or that Liam is not.
- s1: Operations manager is Sam Marino; deputy Yara Ito is **Finance**. No travel report
  has an Operations approver, so truth is 0. The text gives no way to rule out Nadia
  Weber (Perth, $2,809 approved) as Operations; 0 is reachable only as the
  "nothing identifiable" default.

## Classification

| Seed | Verdict | Why |
|---|---|---|
| 0 | **UNDERIVABLE** (also AMBIGUOUS on amount and on the delegate) | Ben Kowalski's division is never stated; key cannot be reached from the text. |
| 1 | **UNDERIVABLE** (key happens to equal the default guess) | No division stated for any approver; 0 is right only because nothing is Operations. |

## Defects (line numbers from evals/independent/fixed/active/Cerebex.py @ 458e2f7)

1. **Division membership is never emitted (UNDERIVABLE, every seed).** `div_of` is
   assigned at lines 99-102/107 and is the sole filter for the truth at lines 246-248,
   but no email ever states a person's division. The only division word in any small
   context (seeds 0-4) is "Operations" in the leave notice (line 231); Engineering /
   Sales / Marketing / Finance occur 0 times. Fix: emit an org-directory email or
   signature lines ("Ben Kowalski, Operations manager") for every manager.
2. **Delegation semantics inverted vs. the question (AMBIGUOUS).** Lines 127-129 pick a
   deputy deliberately *outside* Operations and line 138 routes the delegator's reports
   to that deputy, so delegated reports never count. But the notice (lines 229-232)
   says "all Operations expense approvals go through <Deputy>", and the question says
   the effective approver is "the delegate named in any delegation notice" — the
   natural reading is that delegated approvals are Operations approvals. s0: that
   reading yields 3952 (or 910+3952=4862 if Ben were known). Also the deputy is named by
   first name only, the delegator never receives a request, and the leave notice has a
   random date (line 229) while substitution at line 138 is unconditional (no window).
   Fix: state the deputy's division explicitly and phrase the question as "the
   approver's own home division", or count delegated reports per the notice.
3. **Decision emails cite non-travel reports by a city that never appears (UNRESOLVABLE
   references).** Lines 223-224 write "<First>'s <City> paperwork" for any report, but
   the city is only in the text for travel reports (lines 157-159). Seeds 0-4 contain 15
   such dangling references (e.g. s0 "Yara's Tampere paperwork" = a software-licences
   batch; s1 "Yara's Hanoi paperwork" appears twice for two different non-travel
   reports). A careful reader may treat these as unseen travel requests. First-name-only
   references also collide with the twin-name trap (lines 111-120). Fix: describe the
   paperwork by its category text (catdesc) and full name.
4. **"approve ... at the submitted amount" vs. corrected amount (AMBIGUOUS).** Line 225
   says "at the submitted amount", but truth uses `r["amt"]`, which lines 193/202-203 may
   have overwritten. s0: Austin submitted $704, corrected to $910 (amendment: "use the
   newer figure"), then Ben's decision approves "at the submitted amount" — key 910, but
   704 is a defensible reading. Fix: say "at the corrected amount" or "at $X".
5. **Dates are scrambled.** `_email` (lines 55-56) maps day -> `MONTHS[day%12]`, so
   consecutive days hop months; approvals routinely predate requests (s0 Perth: request
   Dec 6, approval Feb 7) and corrections predate approvals (s0 Riga). "The correction
   governs" can then only be resolved by position, contradicting dates. Fix: derive
   month/day monotonically from `day`.
6. **Truth is 0 in most seeds.** small: 39/50 seeds are 0 (seeds 1-4 all 0); medium 7/10;
   large 2/3 (seeds 0-2). A solver answering "0" scores 1.0 on ~78% of small cells.
   Cause: 1-2 managers per division (line 101), ~20% travel, delegated reports forced out
   of Operations. Fix: guarantee >=2 Operations-approved travel reports per instance.
7. Minor: amendments are sent `From` the requester (line 186) yet announce
   approval/decline decisions ("the decision is now declined" from Carla Marino on her
   own invoice; "we are rescinding the approval" from Nina Cruz on a request that was
   never approved). Plausibility issue, not a key error.
8. Scorer note (line 293): the LAST number is taken as the answer, so "910 (Austin,
   corrected from $704)" scores 0.5 and "Total: $910 — Austin was originally $704"
   scores 0.5; harmless given "Reply with just the number", but brittle.

## Impact on #22

Cerebex small cells (rlm 0/2 exact, plain 1/2 exact in run 1): seed 0 is not
derivable; seed 1's key (0) is reachable by default. Any score on Cerebex at any size
measures luck/defaulting, not long-context reasoning. The plain-model exact hit was
very likely seed 1 (answer 0). Medium/large are affected identically (same code path).
