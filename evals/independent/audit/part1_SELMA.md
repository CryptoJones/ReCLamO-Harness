# Part 1: SELMA answerability (small, seeds 0 and 1)

Question (both seeds): "After reviewing the entire email thread, who is the final owner responsible
for the AI Ethics Review? If no one is currently assigned, respond with 'Unassigned'."

Method: grep the context for every ownership-bearing message (lead/assign/declin/owner/taking
over/review for project). In both seeds, all of them sit in the first ~110 lines, as one block before
the filler. Filler emails never mention the review's ownership. Each ownership message is listed
below in DOCUMENT order, with its Date header.

## Written BEFORE opening the key or the generator

### Seed 0

| # | Date header | Event (quoted) |
|---|---|---|
| 1 | Feb 20, 2023 | Kickoff: "AI Ethics Review for Project Helios ... led by the Product department initially" |
| 2 | Nov 14, 2024 | "assigning the AI Ethics Review for Project Nexus to Skyler Brown from Design" |
| 3 | Jul 27, 2024 | Correction: "Skyler Brown remains the lead" |
| 4 | Dec 3, 2024 | Correction: "Skyler Brown remains the lead" |
| 5 | Aug 12, 2025 | Confirmation: "Skyler Brown from AI Ethics remains the lead" |
| 6 | Dec 10, 2025 | "Taylor Wilson from Product will be taking over" |
| 7 | Oct 7, 2025 | Correction: "Taylor Wilson remains the lead" |
| 8 | Nov 15, 2025 | "Riley Martin from Engineering will be taking over" |
| 9 | Jan 13, 2026 | Correction: "Riley Martin remains the lead" |
| 10 | Mar 15, 2026 | "the previous AI Ethics Review lead has declined ... lead position is unassigned" |
| 11 | Sep 20, 2026 | "assigning the AI Ethics Review for Project Summit to Skyler Martin from AI Ethics" |

- By document order, the final owner is **Skyler Martin**.
- By date, the latest message is also #11 (Sep 20, 2026), so the answer is again **Skyler Martin**.
- The two readings agree. My answer: **Skyler Martin**.

Noise a careful reader trips on:
- Dates are not in document order: #3 predates #2, #7 predates #6, #6 predates #8. Read by date,
  the middle of the chain contradicts itself. #9 says "Riley Martin remains the lead" after #6 handed
  the role to Taylor Wilson.
- Every assignment names a different project (Nexus, then Summit) from the kickoff (Helios). That
  invites a "different review" reading.

The re-run plain answer "Unassigned" would have to stop at #10, or treat the Project Summit
assignment as a different review. Neither is the best reading.

### Seed 1

| # | Date header | Event (quoted) |
|---|---|---|
| 1 | Oct 14, 2023 | Kickoff (Project Helios, Engineering) |
| 2 | Mar 2, 2023 | "assigning the AI Ethics Review for Project Nexus to Jordan Miller from Data Science" |
| 3 | Sep 27, 2024 | "previous ... lead has declined ... position is unassigned" |
| 4 | Apr 17, 2025 | "assigning the AI Ethics Review for Project Catalyst to Skyler Smith from Data Science" |
| 5 | Jan 24, 2026 | Correction: "Skyler Smith remains the lead" |
| 6 | May 3, 2026 | "the AI Ethics Review lead position is now unassigned" |
| 7 | Oct 9, 2026 | "assigning the AI Ethics Review for Project Orion to Jordan Miller from Product" |
| 8 | Oct 15, 2026 | "Jordan Miller from Design will be taking over" |
| 9 | **Jul 7, 2026** | "previous ... lead has declined ... position is unassigned" |

- By document order, the last message is the #9 decline, so the answer is **Unassigned**.
- By date, the latest event is #8 (Oct 15, 2026), so the answer is **Jordan Miller**.
- Read by date, #9 (Jul 7) falls in the gap after #6 (May 3, already unassigned) and before #7.
  There it is a no-op: a "previous lead" declines while nobody holds the role.
- In an email archive, Date headers are the normal ordering signal. The question gives no rule
  saying document order governs.

My answer: **AMBIGUOUS**. Date order gives **Jordan Miller**; document order gives **Unassigned**.
I lean toward Jordan Miller, because the dated reading is internally coherent and the document-order
reading needs a decline sent three months *before* the assignment it cancels. Both runs and both
modes answered Jordan Miller.

## Comparison with the key (after tracing the generator)

See the section appended below.

---

## Comparison with the key (written after opening the generator)

| Seed | Key | My text-only answer | Classification |
|---|---|---|---|
| 0 | Skyler Martin | Skyler Martin (document and date order agree) | **SOUND** (noisy). The re-run plain answer "Unassigned" was the model's own error. |
| 1 | Unassigned | AMBIGUOUS: document order gives Unassigned, date order gives Jordan Miller | **AMBIGUOUS**. The key follows document order. Both runs and both modes answered Jordan Miller, which is the date-order reading. |

### Defect S1: visible Date headers contradict the true event order (`fixed/active/SELMA.py`)
- The ground truth comes from the internal `timeline` (lines 84-154), in order. Line 310 sorts the
  emails by the internal `date_str`, so **document order equals true order**.
- But the Date header the reader sees is a fresh random date within the same year (line 290,
  `_rand_date(rng, year, year)`). Month and day are random, so within a year the headers can run
  backwards. The kickoff header (line 164) is also random within 2023, so assignments can predate
  the kickoff (s1: Mar 2, 2023 vs the Oct 14, 2023 kickoff).
- The question ("After reviewing the entire email thread ... final owner") never says to use
  document order over dates.
- The original generator has the same bug (`generators/SELMA.py:253`, sort at line 273).
- Measured with `scripts/part1_SELMA_orders.py`, a text-only parser that solves both ways.
  Document order matched the key in 200/200 seeds.

| Size | Seeds | Date order ≠ key | Headers out of order |
|---|---|---|---|
| small | 200 | **68 (34%)** | 169 |
| medium | 30 | 11 (37%) | 30 |
| large | 6 | 3 (50%) | 6 |

- Fix: render the header from `date_str` (e.g. `datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")`),
  or make the readable date increase monotonically.

### Defect S2: "Unassigned" is the key most of the time
- 141 of 200 small seeds have "Unassigned" as the key (70%). 22 of 30 medium and 5 of 6 large do too.
- So a constant guess of "Unassigned" scores about 70%.
- Cause: decline (line 125), cancel, and the 10% random unassign at lines 151-153 all set the owner
  to None, and there is no guarantee of a final assignment.
- Fix: balance the final state, e.g. force the last event to an assign/reassign about 50% of the time.

### Defect S3 (minor noise): each assignment names a random project
- Line 186 (`proj = rng.choice(PROJECTS)  # For variety in email`) writes "AI Ethics Review for
  Project <X>", and X differs from the kickoff project (line 48). A careful reader can treat these as
  different reviews.
- The key treats them as one review.
- Fix: use the kickoff's `project` in every assignment.

### Other observations
- Every ownership email sits in one block at the top of the context, before any filler
  (lines 316-345). The "needle" is never actually spread through the haystack, even though meta
  claims "integrate information distributed across the entire context". This is not a correctness
  problem, but it makes the long-context claim hollow.

### #22 impact
In the first run, the SELMA failures at **small s1** (Jordan Miller), **medium s1** (Jamie Thomas)
and **large s0** (Taylor Jackson) all equal the **date-order reading** (see the disagreements list:
small s1 → Jordan Miller, medium s1 → Jamie Thomas, large s0 → Taylor Jackson). Those 4+ "wrong"
answers, counting rlm and plain at small s1, are defensible. The re-run small s1 (rlm) is the same.
Only re-run small s0 plain ("Unassigned" vs Skyler Martin) is a genuine model miss.
