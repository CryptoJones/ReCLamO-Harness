# Task: author ONE independent long-context evaluation task (as a runnable Python generator)

You are helping evaluate a "Recursive Language Model" (RLM) harness. The system under test receives
two strings — a very long CONTEXT and a QUESTION — and returns an ANSWER string. Internally it may run
code over the context and call a language model on pieces of it, but you should treat it as a black box.
The model behind it has a ~32K-token working window; contexts will be far larger than that.

The harness authors wrote their own tests, and we suspect those tests are too easy and shaped to the
harness. We want tests written by someone else: you. Do NOT try to guess how the harness works and do
not design around it. Design a task that a careful human analyst with plenty of time would get right,
but that is genuinely hard to get right without actually reading and reasoning over much of the context.

## Requirements (all mandatory)
1. Deliver a SINGLE self-contained Python 3.11 file in one ```python code block. Standard library only.
2. It must expose: `generate(seed: int, size: str) -> dict` returning
   `{"context": str, "question": str, "answer": <ground truth>, "meta": {...}}`
   with `size` in {"small", "medium", "large"} giving roughly 60K, 300K and 1.2M characters of context.
   And `score(answer_text: str, truth) -> float` in [0, 1], robust to formatting (case, punctuation,
   ordering, extra prose) but NOT lenient about the substance.
3. Fully deterministic given the seed (use `random.Random(seed)`, no time, no network, no files).
4. Ground truth must be computed by the generator from its own data structures — never hand-written.
5. **Grep-resistant**: the answer must not be recoverable by keyword search, regex, or simple counting
   of surface tokens. Use paraphrase, varied vocabulary, distractors, negations, coreference
   ("the latter", "her manager"), corrections later in the text that override earlier statements,
   and facts whose meaning depends on other parts of the document. State in a comment WHY a regex /
   keyword approach fails on your task.
6. **Requires breadth**: the correct answer must depend on information spread across the whole
   context (aggregation, multi-hop joins, temporal reasoning, consistency checking, etc.), not one spot.
7. Natural-looking prose or semi-structured text (emails, logs, minutes, reports, chat) — not
   obviously synthetic key=value lines.
8. Include a short `if __name__ == "__main__":` that prints size stats, the question and the truth for
   seed 0 at each size, and asserts `score(str(truth), truth) == 1.0` and that a few wrong answers score < 1.

## Deliverable format
- One paragraph: the task, what skill it tests, why it is hard, and the main way a solver would fail.
- The single ```python block.
- Nothing else. Do not read or modify any files; you do not need tools for this.


---

# Revision request (round 3: independent audit)

An independent auditor solved your task from the text alone, then traced your generator, and ran 1,701 scorer probes. Findings for your current generator (below):

**Scorer: (~186-194) gives 1.0 to 'Not $11166.59; it is $11366.59' style hedges that list a wrong amount too. Also wording (~121-126): abs(adj) words increases as 'Deduct $X. Adjusted amount: $Y' — say 'increased by' when the adjustment is positive. (Answer key otherwise sound.)**

**SCORER FAIRNESS (applies to every task): score() must give 1.0 to a correct answer in any reasonable format — bare value, a sentence ('The answer is X.'), markdown bold/italics, quotes, bullet list, JSON, trailing period, case changes, numbers with/without $ and thousands commas, extra explanation before/after — and must give < 1.0 (ideally 0) to wrong answers AND to hedged answers that name more than one candidate (e.g. 'A or B', 'not X; it is Y' where X is wrong but listed, two names, two amounts). Add self-test asserts for these formats and hedges across seeds 0-4.**

Return a corrected version that satisfies the whole brief (sizes ~60K/300K/1.2M, deterministic across processes, stdlib only, valid Python 3.11 syntax: no backslashes inside f-string expressions). Keep the task idea and difficulty. Same deliverable format: one paragraph (what you changed) then the single complete ```python block.

## Current generator

```python
import random
import re
from typing import Dict, Any

def generate(seed: int, size: str) -> Dict[str, Any]:
    rng = random.Random(seed)
    
    # Size parameters: (total entries, target chars)
    size_params = {
        "small":  (30, 60000),
        "medium": (120, 300000),
        "large":  (500, 1200000)
    }
    num_entries, target_chars = size_params[size]
    
    # ---------- Data generation ----------
    employees = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank", "Ivy", "Jack"]
    categories = ["Travel", "Office Supplies", "Meals", "Entertainment"]
    months = ["January", "February", "March", "April", "May", "June"]
    
    # Force at least one March travel entry with non-zero final amount (not denied)
    forced_entries = []
    # For small: force 2, medium: 5, large: 10
    num_forced = {"small": 2, "medium": 5, "large": 10}[size]
    for _ in range(num_forced):
        emp = rng.choice(employees)
        month = "March"
        cat = "Travel"
        orig_amount = round(rng.uniform(100, 5000), 2)
        # Add a small adjustment that does not zero out
        adj = round(rng.uniform(-orig_amount*0.3, orig_amount*0.3), 2)
        final_amount = max(1.0, orig_amount + adj)  # ensure >0
        # No denial
        forced_entries.append({
            "employee": emp,
            "month": month,
            "category": cat,
            "orig_amount": orig_amount,
            "adjustments": [adj],
            "final_amount": final_amount,
            "status": "Approved"
        })
    
    # Generate remaining entries randomly
    remaining_entries = []
    for _ in range(num_entries - num_forced):
        emp = rng.choice(employees)
        month = rng.choice(months)
        cat = rng.choice(categories)
        orig_amount = round(rng.uniform(50, 5000), 2)
        num_adjustments = rng.randint(0, 2)
        adjustments = []
        for _ in range(num_adjustments):
            adj_amount = round(rng.uniform(-orig_amount*0.5, orig_amount*0.5), 2)
            adjustments.append(adj_amount)
        final_amount = max(0, orig_amount + sum(adjustments))
        if final_amount == 0 or rng.random() < 0.15:
            status = "Denied"
            final_amount = 0.0
        else:
            status = "Approved"
        remaining_entries.append({
            "employee": emp,
            "month": month,
            "category": cat,
            "orig_amount": orig_amount,
            "adjustments": adjustments,
            "final_amount": final_amount,
            "status": status
        })
    
    # Combine: forced first, then shuffle? We'll shuffle all entries to interleave
    entries = forced_entries + remaining_entries
    rng.shuffle(entries)
    
    # ---------- Text generation ----------
    # Templates with synonyms and coreference
    submission_templates = [
        "From: {emp}\nTo: Finance\nSubject: {month} {cat}\nI have submitted my {cat} expenses for {month}. The total was ${amt:.2f}. Please process.\n",
        "To: Finance\nFrom: {emp}\nRe: {month} {cat} Claim\nAttached is my {cat} request for {month}. Amount: ${amt:.2f}. Kindly approve.\n",
        "Subject: {month} {cat} Reimbursement\nFrom: {emp}\nFinance team,\nPlease find my {cat} expenses for {month} totaling ${amt:.2f}. Thanks.\n"
    ]
    adjustment_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nWe reviewed your claim. Due to policy change, the amount is reduced by ${adj:.2f}. New total: ${new_amt:.2f}.\n",
        "From: {emp}\nTo: Finance\nSubject: Correction to {month} {cat}\nI made an error. The correct amount should be ${new_amt:.2f}, not ${orig_amt:.2f}.\n",
        "From: Manager\nTo: Finance\nRe: {emp}'s {month} {cat}\n{emp}'s trip was partly personal. Deduct ${adj:.2f}. Adjusted amount: ${new_amt:.2f}.\n"
    ]
    denial_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nYour claim is denied because it does not meet policy. No reimbursement.\n",
        "From: Manager\nTo: Finance\nSubject: Deny {emp}'s {month} {cat}\nPlease reject the latter claim. Not approved.\n",
        "From: {emp}\nTo: Finance\nSubject: Withdrawal of {month} {cat}\nI am withdrawing my request. It should be canceled.\n"
    ]
    approval_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nYour claim is approved for ${amt:.2f}. Payment will be issued.\n",
        "From: Finance\nTo: {emp}\nSubject: Approved: {month} {cat}\nWe have approved ${amt:.2f} for your {cat} expenses.\n"
    ]
    filler_templates = [
        "From: IT\nTo: All\nSubject: Network maintenance\nPlease be aware that the network will be down this weekend.\n",
        "From: HR\nTo: All\nSubject: Office party\nJoin us for the annual office party on Friday.\n",
        "From: {emp}\nTo: Manager\nSubject: Vacation request\nI would like to request vacation days in {month}.\n",
        "From: Finance\nTo: {emp}\nSubject: Payroll update\nYour payroll for this month has been processed.\n",
        "To: All\nFrom: CEO\nSubject: Quarterly goals\nLet's achieve our Q2 targets.\n"
    ]
    
    # Build text fragments
    fragments = []
    for entry in entries:
        emp = entry["employee"]
        month = entry["month"]
        cat = entry["category"]
        orig = entry["orig_amount"]
        adjustments = entry["adjustments"]
        final = entry["final_amount"]
        status = entry["status"]
        
        # Submission
        sub = rng.choice(submission_templates).format(emp=emp, month=month, cat=cat, amt=orig)
        fragments.append(sub)
        
        # Adjustments (if any)
        running_amt = orig
        for adj in adjustments:
            running_amt += adj
            new_amt = max(0, running_amt)
            adj_text = rng.choice(adjustment_templates).format(
                emp=emp, month=month, cat=cat, adj=abs(adj), new_amt=new_amt, orig_amt=orig
            )
            fragments.append(adj_text)
        
        # Final status
        if status == "Denied":
            den_text = rng.choice(denial_templates).format(emp=emp, month=month, cat=cat)
            fragments.append(den_text)
        else:
            app_text = rng.choice(approval_templates).format(emp=emp, month=month, cat=cat, amt=final)
            fragments.append(app_text)
    
    # Add filler to reach target length (roughly within 5%)
    current_len = sum(len(f) for f in fragments)
    target_len = target_chars - 5000  # leave room for question and meta
    while current_len < target_len:
        filler = rng.choice(filler_templates).format(emp=rng.choice(employees), month=rng.choice(months))
        fragments.append(filler)
        current_len += len(filler)
    
    # Shuffle fragments to interleave and make it harder to track
    rng.shuffle(fragments)
    context = "".join(fragments)
    # Trim to target if slightly over (rough)
    if len(context) > target_chars:
        context = context[:target_chars]
    
    # ---------- Answer computation ----------
    # Total reimbursed for March travel entries that were not denied
    total = 0.0
    for entry in entries:
        if entry["month"] == "March" and entry["category"] == "Travel" and entry["status"] != "Denied":
            total += entry["final_amount"]
    answer = f"${total:.2f}"
    
    # Question (fixed)
    question = "What is the total amount reimbursed for travel expenses that were originally submitted in March, after all adjustments, excluding any that were ultimately denied?"
    
    meta = {
        "num_entries": len(entries),
        "num_march_travel": sum(1 for e in entries if e["month"]=="March" and e["category"]=="Travel"),
        "num_denied_march_travel": sum(1 for e in entries if e["month"]=="March" and e["category"]=="Travel" and e["status"]=="Denied"),
        "total_approved_march_travel": total,
        "size": size,
        "context_length": len(context)
    }
    
    return {"context": context, "question": question, "answer": answer, "meta": meta}


def score(answer_text: str, truth: Any) -> float:
    # truth is a string like "$123.45"
    # Extract numeric value from answer_text (robust to formatting)
    # Use regex to find a dollar amount (optional $, commas, decimal)
    pattern = r'\$?\s*([\d,]+(?:\.\d{1,2})?)'
    matches = re.findall(pattern, answer_text)
    if not matches:
        return 0.0
    truth_num = float(truth.replace("$", "").replace(",", ""))
    # Check each match for exact numeric equality (within 1 cent)
    for m in matches:
        num_str = m.replace(",", "")
        try:
            num = float(num_str)
            if abs(num - truth_num) < 0.01:
                # Also ensure the answer contains the truth as a substring (normalized)
                norm_answer = answer_text.replace("$", "").replace(",", "").lower().strip()
                norm_truth = truth.replace("$", "").replace(",", "").lower().strip()
                if norm_truth in norm_answer:
                    return 1.0
        except:
            continue
    return 0.0


if __name__ == "__main__":
    for size in ["small", "medium", "large"]:
        result = generate(0, size)
        ctx = result["context"]
        q = result["question"]
        ans = result["answer"]
        meta = result["meta"]
        print(f"Size: {size}")
        print(f"Context length: {len(ctx)} chars")
        print(f"Question: {q}")
        print(f"Truth answer: {ans}")
        print(f"Meta: {meta}")
        # Test score
        assert score(ans, ans) == 1.0, f"Score of truth should be 1.0, got {score(ans, ans)}"
        # Test some wrong answers
        wrong1 = "$0.00"
        wrong2 = "I don't know"
        wrong3 = ans.replace("$", "")  # missing dollar sign but number same
        print(f"Score for truth: {score(ans, ans)}")
        print(f"Score for wrong1 ($0.00): {score(wrong1, ans)}")
        print(f"Score for wrong2: {score(wrong2, ans)}")
        print(f"Score for wrong3 (no $): {score(wrong3, ans)}")
        # Ensure truth is non-zero, so $0.00 is wrong
        assert score(wrong1, ans) < 1.0, f"$0.00 should not score 1.0 against {ans}"
        assert score(wrong2, ans) < 1.0, f"'I don't know' should not score 1.0"
        # wrong3 should be 1.0 because number is same
        assert score(wrong3, ans) == 1.0, f"Expected 1.0 for missing $, got {score(wrong3, ans)}"
        print("All assertions passed.\n")

```
