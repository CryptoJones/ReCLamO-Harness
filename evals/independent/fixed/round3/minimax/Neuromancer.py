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
    # Templates for adjustments. Each template is either a deduction
    # ("reduced by"), an increase ("increased by"), or a self-correction.
    # Sign now matches the actual delta: positive adjustments are worded as
    # increases, negative as deductions. (Originally every adjustment was
    # emitted with abs(adj) and a "reduced by" template, which silently
    # inverted real increases into deductions.)
    deduction_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nWe reviewed your claim. Due to policy change, the amount is reduced by ${adj:.2f}. New total: ${new_amt:.2f}.\n",
        "From: Manager\nTo: Finance\nRe: {emp}'s {month} {cat}\n{emp}'s trip was partly personal. Deduct ${adj:.2f}. Adjusted amount: ${new_amt:.2f}.\n",
        "From: Finance\nTo: {emp}\nSubject: Adjustment to {month} {cat}\nAfter reviewing receipts we are lowering the reimbursement by ${adj:.2f}; the new total is ${new_amt:.2f}.\n",
    ]
    increase_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nAfter reviewing receipts we are increasing the reimbursement by ${adj:.2f}. New total: ${new_amt:.2f}.\n",
        "From: {emp}\nTo: Finance\nSubject: Underestimated {month} {cat}\nI had to revise the claim upward by ${adj:.2f}; the new total is ${new_amt:.2f}.\n",
        "From: Manager\nTo: Finance\nRe: {emp}'s {month} {cat}\nThe {cat} claim was short by ${adj:.2f}; please add it. Adjusted amount: ${new_amt:.2f}.\n",
    ]
    correction_templates = [
        "From: {emp}\nTo: Finance\nSubject: Correction to {month} {cat}\nI made an error. The correct amount should be ${new_amt:.2f}, not ${orig_amt:.2f}.\n",
        "From: Finance\nTo: {emp}\nSubject: Restated total for {month} {cat}\nRestating, the final amount is ${new_amt:.2f} (original ${orig_amt:.2f}).\n",
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
            if adj > 0:
                tpl = rng.choice(increase_templates)
                adj_text = tpl.format(
                    emp=emp, month=month, cat=cat, adj=adj, new_amt=new_amt, orig_amt=orig
                )
            elif adj < 0:
                tpl = rng.choice(deduction_templates)
                adj_text = tpl.format(
                    emp=emp, month=month, cat=cat, adj=-adj, new_amt=new_amt, orig_amt=orig
                )
            else:
                tpl = rng.choice(correction_templates)
                adj_text = tpl.format(
                    emp=emp, month=month, cat=cat, new_amt=new_amt, orig_amt=orig
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
    """Fair scorer: 1.0 for a correct answer in any reasonable format; 0.0
    when the declared final number is wrong or hedged; partial credit when
    the truth appears in the answer but the final number disagrees.

    Number selection rules
    - Strip commas/dollar signs and parse the first run of digits per match.
    - Treat any number that appears with a leading "$" or has a decimal point
      as a candidate for the "real" amount (these are typical money forms).
    - When the last numeric token in the answer is not a money-shaped
      number (e.g. "4 March travel claims"), use the LAST money-shaped
      number as the authoritative figure instead.
    """
    if not isinstance(answer_text, str):
        return 0.0
    try:
        truth_num = round(float(str(truth).replace("$", "").replace(",", "")), 2)
    except (TypeError, ValueError):
        return 0.0
    if not answer_text:
        return 0.0
    pattern = re.compile(r"(\$?\s*[\d,]+(?:\.\d{1,2})?)")
    raw_tokens = pattern.findall(answer_text)
    money_tokens = []
    plain_tokens = []
    for tok in raw_tokens:
        cleaned = tok.replace("$", "").replace(",", "").strip()
        if not cleaned:
            continue
        try:
            v = round(float(cleaned), 2)
        except ValueError:
            continue
        if tok.lstrip().startswith("$") or "." in cleaned:
            money_tokens.append(v)
        else:
            plain_tokens.append(v)
    if not money_tokens and not plain_tokens:
        return 0.0
    if money_tokens:
        final = money_tokens[-1]
        pool = money_tokens
    else:
        final = plain_tokens[-1]
        pool = plain_tokens

    def _close(a, b):
        return abs(a - b) < 0.005

    if _close(final, truth_num):
        other = [n for n in pool[:-1] if not _close(n, truth_num)]
        if other:
            # Truth is the final figure but other candidate numbers present —
            # treat as a hedge. Cap at 0.4 so the audit battery does not flag
            # a hedge as a near-correct answer.
            return 0.4
        return 1.0
    truth_present = any(_close(n, truth_num) for n in pool)
    return 0.4 if truth_present else 0.0


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

    # Scorer regression: wording fix + the formats/hedges the audit flagged.
    for seed in range(5):
        d = generate(seed, "small")
        v = float(d["answer"].replace("$", "").replace(",", ""))
        ok = {
            "bare": d["answer"],
            "dollar": "$" + d["answer"].lstrip("$"),
            "commas": "${:,}".format(v) if "." not in str(v) else "${:,.2f}".format(v),
            "sentence": "After applying every amendment the total is " + d["answer"] + ".",
            "bold": "**" + d["answer"] + "**",
            "sentence_bold": "The reimbursed total is **" + d["answer"] + "**.",
            "lower": d["answer"].lower(),
            "trailing_period": d["answer"] + ".",
            "code_span": "`" + d["answer"] + "`",
            "trailing_explanation": d["answer"] + " (after applying all corrections)",
            "lead_in": "After applying every adjustment, the reimbursed total comes to " + d["answer"] + ".",
        }
        for k, s in ok.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, f"Neuromancer positive {k!r} should score 1.0 (seed={seed}); got {sc}"
        # Format with cents (matches if truth has no decimal)
        cents = "${:.2f}".format(v)
        if cents == d["answer"]:
            assert score(cents, d["answer"]) == 1.0
        # Hedging between two totals
        hedge = "Either ${:.2f} or ${:.2f}".format(v - 100, v)
        assert score(hedge, d["answer"]) < 1.0
        # Negated truth
        neg = "Not ${:.2f}; it is ${:.2f}".format(v, v + 200)
        assert score(neg, d["answer"]) < 1.0
        # Off by a cent
        cents_off = "${:.2f}".format(v + 0.01)
        assert score(cents_off, d["answer"]) < 1.0
    print("Neuromancer: scorer regression battery PASS.")

    # Wording-defect regression: a positive adjustment must NOT be phrased as
    # "reduced by" or "Deduct". Originally every adjustment was emitted with
    # abs(adj) and a deduction template, so an increase of +50 became "the
    # amount is reduced by $50.00". The fix picks the template family based
    # on the actual sign of the adjustment.
    import re as _re_n
    for seed in range(10):
        d = generate(seed, "small")
        ctx = d["context"]
        # Split the context by the "From:" header lines. Each block is one
        # claim (or filler). A block that contains both "reduced by $X" and
        # a "New total: $Y" must satisfy Y <= original; if not, the wording
        # is wrong (the deductible $X actually increased the running total).
        blocks = re.split(r"(?=^From: )", ctx, flags=re.M)
        for block in blocks:
            deduct_match = re.search(
                r"reduced by \$([\d.,]+)\.\s*New total: \$([\d.,]+)", block
            )
            orig_match = re.search(
                r"total(?:ing| came to| is)? \$([\d.,]+)", block
            )
            if deduct_match and orig_match:
                deduct = float(deduct_match.group(1).replace(",", "").rstrip("."))
                new_total = float(deduct_match.group(2).replace(",", "").rstrip("."))
                orig_total = float(orig_match.group(1).replace(",", "").rstrip("."))
                # In a correct deduction, new_total = orig - deduct.
                if orig_total - deduct - new_total > 0.5:
                    raise AssertionError(
                        "Neuromancer wording defect (seed=" + str(seed) + "): "
                        "'reduced by $" + str(deduct) + "', New total: $"
                        + str(new_total) + ", but original total was $"
                        + str(orig_total) + " (would only match an increase)."
                    )
    print("Neuromancer: wording-defect regression PASS (no positive-stated-as-deduction).")
