# Part 1 — TheDixieFlatline answerability (small, seeds 0 and 1)

Method: text-only parse (`scripts/part1_TheDixieFlatline_view.py`) that prints the
non-noise messages (drops Lunch/Cleaning/Outage/Status report/Policy update/Distractor
Asset/Re: Move, which only contain rumours or other assets). Dates in both contexts are
monotonically increasing (407 messages each), so file order == time order.

## Step 1 — my answers, written BEFORE opening the key

### Seed 0 — my answer: **Datacenter Beta**

Rename chain (all from "Director -> All | Codename Update"):
- 1674875799 `'The Genesis Drive' will now be known as 'The Ghost Matrix 14'`
- 1676280944 `'The Ghost Matrix 14' will now be known as 'The Stone Archive 90'`
- 1699910879 `'The Stone Archive 90' will now be known as 'The Void Matrix 81'`

Custody chain:
- Rita -> Frank -> Paula -> Grace -> Steve -> Rupert -> Orson (all `Confirming I have physically handed 'The Stone Archive 90' to you.`)
- 1707245448 Orson -> Ulysses, 1707969543 Ulysses -> Victor (`'The Void Matrix 81'`)
- 1711332341 `<000347> Victor -> HR Lead | I have left 'The Void Matrix 81' on the desk of the HR Lead.`  (last custody event)

Who is HR Lead: `<setup_0031> Heidi -> All | Hi everyone, I will be serving as your HR Lead.`
No later "Personnel Change" touches HR Lead (the only one: Arthur becomes Chief Janitor).

Heidi's location: `<setup_0016> IT -> Heidi | We activated the ethernet port in your workspace at Datacenter Beta.`
No "Office Relocation" approval for Heidi; no rumour even mentions Heidi moving.

Late traps (ignored, correctly): `<999998> Auditor -> Heidi | I heard 'The Void Matrix 81' is going to be moved to Room 112 tomorrow. Keep it safe in your current office until then.` (rumour; also confirms Heidi holds it) and `<999999> IT -> All | ... please bring it to Room 137 by next Friday` (a request, not a move).

### Seed 1 — my answer: **Room 111**

Renames: Genesis Drive -> Iron Matrix 69 (1679248413) -> Alpha Matrix 26 (1682511503) -> Omega Key 97 (1689100939) -> Iron Protocol 15 (1712248033).

Custody:
- 1673710133 `Yusuf -> Lead Auditor | I have left 'The Genesis Drive' on the desk of the Lead Auditor.` Lead Auditor then = Frank (`<setup_0016> Frank -> All | ... your Lead Auditor.`)
- 1677571937 `Frank -> Compliance Officer | I have left 'The Genesis Drive' on the desk of the Compliance Officer.` = George (`<setup_0007> ... George is our Compliance Officer.`)
- 1682624790 `George -> Director of Security | I have left 'The Alpha Matrix 26' on the desk of the Director of Security.` = Judy (`<setup_0005>`)
- Judy -> Manny (1683754356), Manny -> Eve (1688872392), Eve -> Niaj (1690092520) — "physically handed"
- 1693323582 `Niaj -> HR Lead | I have left 'The Omega Key 97' on the desk of the HR Lead.` (last custody event)

Trap: 1688049567 `Please welcome Carl, who is taking over as the new Lead Auditor` — irrelevant, Frank had already passed the asset on at 1677571937.

HR Lead = Tina (`<setup_0011> HR -> All | Direct all HR Lead inquiries to Tina.`), never replaced.
Tina's workspace: `<setup_0004> IT -> Tina | We activated the ethernet port in your workspace at Room 111.`
No approved "Office Relocation" for Tina; only rumours (`I heard Tina is thinking of moving to Room 143` / `Room 131`).
Late traps: `<999998> Auditor -> Tina | ... going to be moved to Room 106 tomorrow. Keep it safe in your current office` and `<999999> ... bring it to Room 149`.

## Step 2 — comparison with the key (opened only after Step 1 was written)

| Seed | My answer | Key | Match | Classification |
|---|---|---|---|---|
| 0 | Datacenter Beta | Datacenter Beta | yes | **SOUND** (HARD-BUT-FAIR: 3 renames, desk-of-role hop, two end-of-log traps) |
| 1 | Room 111 | Room 111 | yes | **SOUND** (HARD-BUT-FAIR: 4 renames, 3 desk-of-role hops, a Lead Auditor reassignment trap) |

Both cells are derivable from the text alone; neither contains a decoy "Handing over" as the
last custody event, nor a role reassignment / relocation after a desk drop. So the plain and
RLM failures on these two cells in the re-run are model errors, not task defects (modulo the
scorer: answers longer than truth+50 chars score 0.5, see Part 2).

## Step 3 — systematic defects found in the generator (fixed/active/TheDixieFlatline.py)

### D1 — the CORRECTION message is never emitted -> UNDERIVABLE key (severe, ~17% of seeds)
- Lines 159-168 build two messages for `action == "correction"`: a decoy
  `Subject: Handing over / I gave '<alias>' to you just now.` (to `fake_holder`, appended at
  line 163) and `Subject: CORRECTION ... I actually gave '<alias>' to <new_holder>` (`body`, line 167).
- Line 170 `if action != "correction": messages.append(...)` skips appending `body` for exactly
  that action, so **the correction is dropped**, while line 168 still sets
  `current_holder = new_holder`. The text tells the reader the asset went to `fake_holder`; the
  key follows the never-stated `new_holder`.
- `grep -c CORRECTION` on every generated context = 0.
- When the decoy is the last custody-type message, the final holder is never named anywhere,
  so the answer cannot be derived (the only defensible text answer is the decoy recipient's office).
  Mid-chain decoys are recoverable only because the next transfer's `From:` names the real holder,
  which contradicts the decoy.
- Measured with `scripts/part1_TheDixieFlatline_quantify.py` (text-only solver, all disagreements
  explained by this one cause, 0 other diffs):
  - small: 34/200 seeds UNDERIVABLE (e.g. 12, 14, 19, 22, 26, 30, 36, 38, 43, 52, ...); decoy present in 171/200
  - medium: 7/40 (8, 10, 13, 19, 23, 24, 35)
  - large: 4/10 (2, 3, 5, 6)
  - seeds 0-4 small: none affected; #22 active cells (small 0/1, medium 0/1, large 0): none affected.
  - Worked example, small seed 52: last custody message `Paula -> Rita | Handing over | I gave 'The Null Drive 32' to you just now.`; key = office of Doris (meta final_holder), who never appears as a recipient.
- The same bug is in the original `generators/TheDixieFlatline.py` (line 142). In the **first #22 run**
  (original version) **medium seed 1** ended on a decoy (`I gave 'The Black File 28' to you just now.`),
  so that cell was underivable for this reason too, on top of the missing-setup defect fixed in round 2.
- Fix: append both messages (`messages.append(f"{msg_header}\n{body}")` for the correction too), i.e. drop the `action != "correction"` guard at line 170.

### D2 — malformed Date header on the decoy (cosmetic, but breaks naive parsers)
- Line 163 `f"{msg_header}a\n{msg1}"` appends `a` to the end of the header, i.e. to the Date
  value (`Date: 1676119488a`), not to the Message-ID. Present in 171/200 small contexts. A solver
  doing `int(date)` crashes (mine did).
- Fix: build the header as `Message-ID: <{i:06d}a@corp.local>\nDate: {timestamp}`.

### D3 — desk-of-role semantics are unstated (minor ambiguity)
- Line 156/157: "left on the desk of the <role>" binds the asset to the *person* holding the role
  at that moment (`current_holder = role_to_person[...]`). Lines 127-131 may later reassign that
  role, and lines 133-137 may relocate that person; the key assumes the asset follows the person,
  not the desk. A reader could defend "the new <role>'s office" or "the old desk's room".
- Frequency (small): role reassigned after a desk drop with the asset still there in 18/200;
  holder relocated after a desk drop in 6/200. In every such case my text reading agreed with the
  key, so this is a judgment call, not a wrong key. Large seed 0 (a #22 cell) has the
  role-reassignment pattern; large seed 1 has both.
- Fix: make the handoff text name the person ("left it on Heidi's desk (HR Lead)") or have
  `assign_role` skip a role whose desk currently holds the asset.

### Not defects (checked)
- Dates are strictly increasing in file order; renames chain cleanly from 'The Genesis Drive'.
- Initial roles/offices are now stated (round-2 fix); the end-of-log traps exclude the true location (lines 184, 190).
- The true room appearing in noise (Lunch/Outage/Cleaning/Re: Move) is a fair distractor, not ambiguity.
