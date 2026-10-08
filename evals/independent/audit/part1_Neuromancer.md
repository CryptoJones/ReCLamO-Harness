# Part 1 — Neuromancer (small), blind solve

Question (both seeds): total amount reimbursed for travel expenses originally submitted in March,
after all adjustments, excluding any ultimately denied.

Observation before solving: messages are in no chronological order (e.g. seed 0 Eve's approval at
ctx line 911 precedes her submission at 1447 and her correction at 2055), and there are no dates, so
"final" cannot be read from position. The Finance approval message ("Your claim is approved for $X" /
"We have approved $X") is the only message that states the amount actually reimbursed, so I sum those.

## Seed 0 — my answer: 11166.59

| Claimant | Evidence (ctx line) | Reimbursed |
|---|---|---|
| Bob | 987 "Attached is my Travel request for March. Amount: $2744.38"; 527 "Re: March Travel / Your claim is approved for $2744.38" | 2744.38 |
| Grace | 811 request $3813.98; 1427 "Deduct $181.76. Adjusted amount: $3632.22"; 1607 approved $3632.22 | 3632.22 |
| Eve | 1447 submitted $4830.78; 2055 "correct amount should be $4789.99"; 911 approved $4789.99 | 4789.99 |

No March Travel denials or withdrawals. Chain is internally consistent. 2744.38+3632.22+4789.99 = 11166.59.

## Seed 1 — my answer: 12341.12 (with a defensible alternative 13063.81)

| Claimant | Evidence | Reimbursed |
|---|---|---|
| Bob (claim A) | 13-16 March Travel $1349.84; 1651 "Deduct $3.70. Adjusted amount: $1346.14"; 223 approved $1346.14 | 1346.14 |
| Bob (claim B) | 1127 submitted $160.49; 1603 "reduced by $6.65. New total: $167.14"; 1027 "Deduct $70.48. Adjusted amount: $237.62"; 623 approved $237.62 | 237.62 |
| Hank | 147 submitted $1949.26; 1827 correction to $1250.94; 719 "Deduct $24.37. Adjusted amount: $1973.63"; 1519 approved $1250.94 | 1250.94 (?) |
| Alice | 1351 submitted $4299.65; 471 "Deduct $1793.71. Adjusted amount: $6093.36"; 327 approved $6093.36 | 6093.36 |
| Carol | 1939 submitted $2889.10; 1743 "Deduct $523.96. Adjusted amount: $3413.06"; 1511 approved $3413.06 | 3413.06 |

Sum of approvals = 12341.12. Problems seen in the text:
- Arithmetic doesn't hold: Alice 4299.65 − 1793.71 ≠ 6093.36 (an increase!); Carol 2889.10 − 523.96 ≠ 3413.06;
  Bob B 160.49 − 6.65 ≠ 167.14, and 167.14 − 70.48 ≠ 237.62; Hank 1250.94 − 24.37 ≠ 1973.63.
- Hank has two conflicting finals (approval 1250.94 vs manager adjustment 1973.63) and no ordering to
  break the tie. If the manager deduction is taken as the last adjustment, the total is 13063.81.
- Bob has two separate March Travel claims with identical subject lines; the $167.14 policy note
  cannot be attributed to either one from the text.
