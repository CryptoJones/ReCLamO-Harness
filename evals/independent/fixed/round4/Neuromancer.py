import random
import re
from typing import Dict, Any, List, Tuple

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
    num_forced = {"small": 2, "medium": 5, "large": 10}[size]
    forced_entries = []
    for _ in range(num_forced):
        emp = rng.choice(employees)
        month = "March"
        cat = "Travel"
        orig_amount = round(rng.uniform(100, 5000), 2)
        adj = round(rng.uniform(-orig_amount*0.3, orig_amount*0.3), 2)
        final_amount = max(1.0, orig_amount + adj)
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

    entries = forced_entries + remaining_entries
    rng.shuffle(entries)

    # ---------- Text generation ----------
    submission_templates = [
        "From: {emp}\nTo: Finance\nSubject: {month} {cat}\nI have submitted my {cat} expenses for {month}. The total was ${amt:.2f}. Please process.\n",
        "To: Finance\nFrom: {emp}\nRe: {month} {cat} Claim\nAttached is my {cat} request for {month}. Amount: ${amt:.2f}. Kindly approve.\n",
        "Subject: {month} {cat} Reimbursement\nFrom: {emp}\nFinance team,\nPlease find my {cat} expenses for {month} totaling ${amt:.2f}. Thanks.\n"
    ]

    # Adjustment templates – now direction‑aware
    inc_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nWe reviewed your claim. Due to a policy change, the amount is increased by ${abs_adj:.2f}. New total: ${new_amt:.2f}.\n",
        "From: {emp}\nTo: Finance\nSubject: Correction to {month} {cat}\nI made an error. The correct amount should be ${new_amt:.2f}, not ${orig_amt:.2f}. (This is an increase.)\n",
        "From: Manager\nTo: Finance\nRe: {emp}'s {month} {cat}\n{emp}'s trip was partly business. Add ${abs_adj:.2f}. Adjusted amount: ${new_amt:.2f}.\n"
    ]
    dec_templates = [
        "From: Finance\nTo: {emp}\nRe: {month} {cat}\nWe reviewed your claim. Due to a policy change, the amount is reduced by ${abs_adj:.2f}. New total: ${new_amt:.2f}.\n",
        "From: {emp}\nTo: Finance\nSubject: Correction to {month} {cat}\nI made an error. The correct amount should be ${new_amt:.2f}, not ${orig_amt:.2f}. (This is a reduction.)\n",
        "From: Manager\nTo: Finance\nRe: {emp}'s {month} {cat}\n{emp}'s trip was partly personal. Deduct ${abs_adj:.2f}. Adjusted amount: ${new_amt:.2f}.\n"
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

        # Adjustments
        running_amt = orig
        for adj in adjustments:
            running_amt += adj
            new_amt = max(0, running_amt)
            abs_adj = abs(adj)
            if adj >= 0:
                adj_text = rng.choice(inc_templates).format(
                    emp=emp, month=month, cat=cat, abs_adj=abs_adj, new_amt=new_amt, orig_amt=orig
                )
            else:
                adj_text = rng.choice(dec_templates).format(
                    emp=emp, month=month, cat=cat, abs_adj=abs_adj, new_amt=new_amt, orig_amt=orig
                )
            fragments.append(adj_text)

        # Final status
        if status == "Denied":
            den_text = rng.choice(denial_templates).format(emp=emp, month=month, cat=cat)
            fragments.append(den_text)
        else:
            app_text = rng.choice(approval_templates).format(emp=emp, month=month, cat=cat, amt=final)
            fragments.append(app_text)

    # Add filler to reach target length
    current_len = sum(len(f) for f in fragments)
    target_len = target_chars - 5000
    while current_len < target_len:
        filler = rng.choice(filler_templates).format(emp=rng.choice(employees), month=rng.choice(months))
        fragments.append(filler)
        current_len += len(filler)

    rng.shuffle(fragments)
    context = "".join(fragments)
    if len(context) > target_chars:
        context = context[:target_chars]

    # ---------- Answer computation ----------
    total = 0.0
    for entry in entries:
        if entry["month"] == "March" and entry["category"] == "Travel" and entry["status"] != "Denied":
            total += entry["final_amount"]
    answer = f"${total:.2f}"

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


# Round 4 (2026-10-19, issue #95): final-statement scoring; see evals/TEST-PLAN.md section 1d.
# --- round-4 shared helpers (pasted verbatim into every round-4 scorer; keep in sync) ---
# Round 4 (2026-10-19, issue #95): a scorer reads the answer's FINAL STATEMENT, not its working.
# Formatting is normalised first (LaTeX money, \boxed{}, markdown emphasis, tables), then the
# final segment is located, and "hedge" means an explicit alternative offered inside that
# segment ("X or Y", "either X or Y", "possibly X"), never the mere presence of other numbers
# or names earlier in a shown calculation. Both arms are scored by the same code.
import re as _re4

_R4_MARKER = _re4.compile(
    r"(?im)^[\s#>*_|\-]*(?:final\s+answer|final\s+result|final\s+total|answer|conclusion|"
    r"result|in\s+summary|summary|therefore|so,?\s+the|thus,?\s+the|hence|total)\b"
)
_R4_ALT = _re4.compile(
    r"\b(?:either|alternatively|possibly|probably|maybe|perhaps|could\s+be|might\s+be|"
    r"can(?:no|')t\s+(?:be\s+)?determine[d]?|unclear|ambiguous|uncertain)\b|"
    r"\b(?:or)\b",
    _re4.IGNORECASE,
)


def _r4_normalize(text: str) -> str:
    """Flatten LaTeX / markdown money and emphasis so one regex sees one surface form."""
    t = text.replace("\u2212", "-").replace("\u00a0", " ")
    t = t.replace("{,}", ",").replace("\\$", "$").replace("\\,", "").replace("\\!", "")
    for _ in range(3):  # nested \boxed{\text{...}} etc.
        t = _re4.sub(r"\\(?:boxed|text|textbf|mathrm|mathbf|underline)\{([^{}]*)\}", r"\1", t)
    t = t.replace("$$", " ")
    t = _re4.sub(r"\\\(|\\\)|\\\[|\\\]", " ", t)
    t = _re4.sub(r"(\*\*|__)(.+?)\1", r"\2", t, flags=_re4.DOTALL)
    t = _re4.sub(r"`+", "", t)
    t = _re4.sub(r"^\s*\|?[\s:\-|]+\|?\s*$", "", t, flags=_re4.MULTILINE)  # table rules
    t = t.replace("|", " ")
    return t


def _r4_segment(text: str) -> str:
    """The final statement: from the last answer marker to the end, else the last paragraph.

    A marker is a line that opens with "final answer", "answer", "conclusion", "total",
    "therefore" and the like. If no marker exists the last non-empty paragraph is used.
    Callers widen to the whole text when the segment holds no candidate of the kind they
    need (for example a name when the total line carries only the amount).
    """
    t = text.rstrip()
    if not t:
        return ""
    last = None
    for m in _R4_MARKER.finditer(t):
        last = m
    if last is not None:
        return t[last.start():]
    paras = [p for p in _re4.split(r"\n\s*\n", t) if p.strip()]
    return paras[-1] if paras else t


def _r4_explicit_alternative(segment: str) -> bool:
    """True when the final statement itself offers alternatives or declares uncertainty."""
    return bool(_R4_ALT.search(segment))
# --- end round-4 shared helpers ---

# --- round-4 lane helpers (this file only; same text in every round-4 scorer that uses them) ---
_R4_ALT_ANY = _re4.compile(
    r"\b(?:possibly|probably|maybe|perhaps|could\s+be|might\s+be|"
    r"can(?:no|')t\s+(?:be\s+)?determine[d]?|unclear|ambiguous|uncertain)\b",
    _re4.IGNORECASE,
)
_R4_ALT_LINK = _re4.compile(r"\b(?:or|either|alternatively)\b", _re4.IGNORECASE)


def _r4_hedged(segment: str, spans) -> bool:
    """Rule 3, read strictly: at least two DISTINCT candidates in the segment AND the
    alternative is offered between them ("X or Y", "either X or Y"), or the segment declares
    uncertainty outright ("possibly", "cannot be determined"). A bare "or" elsewhere in the
    segment ("unassigns or reassigns", "denied or withdrawn") is not a hedge.
    spans: iterable of (start, end, key) for candidate occurrences inside segment."""
    spans = list(spans)
    keys = {k for _, _, k in spans}
    if len(keys) < 2 or not _r4_explicit_alternative(segment):
        return False
    if _R4_ALT_ANY.search(segment):
        return True
    ordered = sorted(spans, key=lambda x: (x[0], x[1]))
    for (s1, e1, k1), (s2, e2, k2) in zip(ordered, ordered[1:]):
        if k1 != k2 and s2 - e1 <= 80 and _R4_ALT_LINK.search(segment[e1:s2]):
            return True
    return False


def _r4_lead(text: str) -> str:
    """Answer-first layout: a short standalone first line ("**Unassigned**", "**Room 130**",
    "**$4,311.31**") followed by the explanation. Returned only when the text has more than
    one paragraph, the first paragraph is a single line of at most 80 chars, and no answer
    marker ("Final answer", "Therefore", ...) opens a later line (that later line is then the
    final statement, not the lead); else ""."""
    t = text.strip()
    paras = [p for p in _re4.split(r"\n\s*\n", t) if p.strip()]
    if len(paras) < 2:
        return ""
    first = paras[0].strip()
    if "\n" in first or len(first) > 80:
        return ""
    last = None
    for m in _R4_MARKER.finditer(t):
        last = m
    if last is not None and last.start() >= len(first):
        return ""
    return first
# --- end round-4 lane helpers ---

# --- round-4 amount helpers (this file only; same text in MasterControl and Neuromancer) ---
_R4_DATE = _re4.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_R4_MONEY = _re4.compile(
    r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)|(?<![\d.$])(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?!\d)"
)
_R4_BARE = _re4.compile(r"(?<![\d.,$])(\d{1,3}(?:,\d{3})+|\d{2,7})(?![\d.,]?\d)")
_R4_NEG_BEFORE = _re4.compile(
    r"(?:\b(?:not|never|wrong(?:ly)?|incorrect(?:ly)?|instead\s+of|rather\s+than)\b"
    r"[^\d$\n]{0,20}|\bno\s*)$",
    _re4.IGNORECASE,
)
_R4_NEG_AFTER = _re4.compile(
    r"^[^\d$\n]{0,12}\b(?:is|are|was|were)(?:\s+both)?\s+(?:wrong|incorrect)\b", _re4.IGNORECASE
)
_R4_NEG_LIST = _re4.compile(r"^\s*(?:,|and|&)\s*$", _re4.IGNORECASE)
_R4_OPERATOR = _re4.compile(r"^[^\n=]{0,60}(?:\+|\bplus\b|\bminus\b)[^\n=]{0,60}$", _re4.IGNORECASE)


def _r4_amounts(text: str):
    """Every dollar figure in text with its position and three flags: negated ("not $X",
    "$X is wrong"), operand (sits in a shown sum: "$a + $b", "$a plus $b"), paren (inside a
    parenthetical aside). Figures with a "$" or cents are preferred; bare integers are used
    only when the text has none of those. ISO dates are blanked first."""
    t = _R4_DATE.sub(lambda m: " " * (m.end() - m.start()), text)
    found = []
    for m in _R4_MONEY.finditer(t):
        raw = m.group(1) or m.group(2)
        try:
            found.append((m.start(), m.end(), round(float(raw.replace(",", "")), 2)))
        except ValueError:
            continue
    if not found:
        for m in _R4_BARE.finditer(t):
            try:
                found.append((m.start(), m.end(), round(float(m.group(1).replace(",", "")), 2)))
            except ValueError:
                continue
    out = []
    for i, (s, e, v) in enumerate(found):
        neg = bool(_R4_NEG_BEFORE.search(t[max(0, s - 24):s])) or bool(_R4_NEG_AFTER.match(t[e:e + 40]))
        gaps = []
        if i > 0:
            gaps.append(t[found[i - 1][1]:s])
        if i + 1 < len(found):
            gaps.append(t[e:found[i + 1][0]])
        oper = any(_R4_OPERATOR.match(g) for g in gaps)
        paren = t[:s].count("(") > t[:s].count(")")
        out.append({"start": s, "end": e, "value": v, "neg": neg, "oper": oper, "paren": paren})
    # "$X and $Y are both wrong": the trailing negation covers the whole list.
    for i in range(len(out) - 1, 0, -1):
        if out[i]["neg"] and _R4_NEG_LIST.match(t[out[i - 1]["end"]:out[i]["start"]]):
            out[i - 1]["neg"] = True
    return out


def _r4_pick_amount(text: str):
    """(authoritative amount or None, candidate list). The authoritative amount is the LAST
    figure that is not an operand of a shown sum, not a parenthetical aside (when a figure
    outside parentheses exists) and not negated; the candidates are what a hedge is judged on."""
    am = _r4_amounts(text)
    if not am:
        return None, []
    cands = [a for a in am if not a["oper"]] or am
    if any(not a["paren"] for a in cands):
        cands = [a for a in cands if not a["paren"]]
    clean = [a for a in cands if not a["neg"]]
    return (clean or cands)[-1]["value"], cands
# --- end round-4 amount helpers ---


def _r4_same_cents(a: float, b: float) -> bool:
    """Equal to the cent: a half-cent tolerance, so $X.13 is not $X.12."""
    return abs(a - b) < 0.005


def score(answer_text: str, truth: Any) -> float:
    """Round-4 scorer for Neuromancer: grades the FINAL STATEMENT.

    The answer is normalised (LaTeX money, \\boxed{}, markdown), the final segment located,
    and the authoritative amount is the LAST clean figure in it: not an operand of a shown
    sum ("$a + $b = $T" -> T), not a parenthetical breakdown after the total, not negated
    ("not $X"). 1.0 iff that amount equals the truth within a cent and the segment does not
    offer an explicit alternative between two amounts; 0.0 otherwise. Equality is to the cent
    (half-cent tolerance), so an off-by-a-cent figure is wrong. Shown working is never a
    penalty; a wrong final figure is wrong even if the truth appears in the working.
    """
    if not isinstance(answer_text, str) or not isinstance(truth, str):
        return 0.0
    try:
        truth_num = float(truth.replace("$", "").replace(",", ""))
    except ValueError:
        return 0.0
    norm = _r4_normalize(answer_text)
    if not norm.strip():
        return 0.0
    seg = _r4_segment(norm)
    val, cands = _r4_pick_amount(seg)
    scope = seg
    if val is None:
        val, cands = _r4_pick_amount(norm)
        scope = norm
    if val is None:
        return 0.0
    if not _r4_same_cents(val, truth_num):
        # Answer-first layout: "**$X**" then an explanation that does not restate X.
        lead = _r4_lead(norm)
        lval, lcands = _r4_pick_amount(lead) if lead else (None, [])
        if lval is None or not _r4_same_cents(lval, truth_num):
            return 0.0
        val, cands, scope = lval, lcands, lead
    if _r4_hedged(scope, [(a["start"], a["end"], a["value"]) for a in cands]):
        return 0.0
    return 1.0

if __name__ == "__main__":
    for seed in range(5):
        for size in ["small", "medium", "large"]:
            result = generate(seed, size)
            ctx = result["context"]
            q = result["question"]
            ans = result["answer"]
            meta = result["meta"]
            print(f"Seed {seed}, Size {size}: context length {len(ctx)} chars, truth {ans}")

            # Basic correctness
            assert score(ans, ans) == 1.0, f"Truth should score 1.0, got {score(ans, ans)}"

            # Test various correct formats (should all score 1.0)
            truth_num = float(ans.replace("$", "").replace(",", ""))
            correct_formats = [
                f"${truth_num:.2f}",                                          # exact
                f"${truth_num:.2f}.",                                        # trailing period
                f"The answer is ${truth_num:.2f}",                           # sentence
                f"**${truth_num:.2f}**",                                     # markdown bold
                f"*${truth_num:.2f}*",                                       # markdown italics
                f"`${truth_num:.2f}`",                                       # code
                f"\"${truth_num:.2f}\"",                                     # quotes
                f"${truth_num:,.2f}",                                        # with thousands comma
                f"{truth_num:.2f}",                                          # no dollar sign
                f"The total reimbursed amount is ${truth_num:.2f}.",         # extra prose before
                f"Answer: ${truth_num:.2f}.",                                # label
                f"{{ \"amount\": ${truth_num:.2f} }}",                      # JSON-like
                f"- ${truth_num:.2f}\n- Other stuff",                        # bullet list with extra
            ]
            for fmt in correct_formats:
                sc = score(fmt, ans)
                assert sc == 1.0, f"Format '{fmt}' should score 1.0, got {sc}"

            # Test hedges (should score 0.0): an explicit alternative between amounts in the
            # final statement, or a final statement that rejects every amount it names.
            hedge_formats = [
                f"${truth_num+1:.2f} or ${truth_num:.2f}",
                f"Maybe ${truth_num:.2f} or ${truth_num+2:.2f}",
                f"Either ${truth_num:.2f} or ${truth_num+1:.2f}",
                f"${truth_num:.2f} and ${truth_num+3:.2f} are both wrong",
            ]
            for hedge in hedge_formats:
                sc = score(hedge, ans)
                assert sc == 0.0, f"Hedge '{hedge}' should score 0.0, got {sc}"
            # Round 4 (issue #95): these used to be expected 0.0 under the old "negated amount
            # anywhere" rule. Their FINAL statement is the truth ("it is $X", "correct: $X") and
            # the negated figure is skipped when picking the authoritative amount, so they are
            # right answers: 1.0.
            negated_then_stated = [
                f"Not ${truth_num+1:.2f}; it is ${truth_num:.2f}",
                f"The answer is not ${truth_num+5:.2f}, it is ${truth_num:.2f}",
                f"Incorrect: ${truth_num+10:.2f}; correct: ${truth_num:.2f}",
            ]
            for s in negated_then_stated:
                sc = score(s, ans)
                assert sc == 1.0, f"Negated-then-stated '{s}' should score 1.0 under round 4, got {sc}"

            # Test clearly wrong answers
            wrongs = [
                "$0.00",
                "I don't know",
                "No idea",
                f"${truth_num+100:.2f}",
                "None",
                "zero",
                "The amount is $999.99",
            ]
            for w in wrongs:
                sc = score(w, ans)
                assert sc < 1.0, f"Wrong answer '{w}' should score <1.0, got {sc}"

            # Test that answer with only truth and no extra amounts works
            extra_prose = f"After reviewing all records, the total reimbursement for March travel is ${truth_num:.2f}. This includes adjustments and excludes denials."
            assert score(extra_prose, ans) == 1.0, f"Extra prose should score 1.0, got {score(extra_prose, ans)}"

        print(f"Seed {seed}: all assertions passed.\n")
    print("All seeds and sizes passed.")

    # ----- Round 4 (issue #95): final-statement scoring -----
    # The recorded plain answers end in a LaTeX sum ("$$\$a + \$b$$ **= $T**" or
    # "= \boxed{\$T}"), a markdown table with a total row, or "Total: $a + $b = $T"; the
    # harness arm sometimes adds a parenthetical breakdown after the total. All of these are
    # right answers and must score 1.0. A wrong final figure stays 0.0 even when the truth
    # appears in the working, and "either $a or $b" in the final segment is 0.0.
    def _lt(v):
        return ("\\$%s" % format(v, ",.2f")).replace(",", "{,}")

    def _bare(v):
        return format(v, ",.2f").replace(",", "{,}")

    for seed in range(5):
        for size in ["small", "medium"]:
            ans = generate(seed, size)["answer"]
            v = float(ans.replace("$", "").replace(",", ""))
            a1 = round(v * 0.4, 2)
            a2 = round(v - a1, 2)
            r4_pos = {
                "table_total_row": (f"| Employee | Approved |\n|---|---|\n| Bob | ${a1:,.2f} |\n| Eve | ${a2:,.2f} |\n"
                                    f"| **Total** | **${v:,.2f}** |"),
                "table_then_bold_total": (f"| Employee | Approved |\n|---|---|\n| Bob | ${a1:,.2f} |\n"
                                          f"| Eve | ${a2:,.2f} |\n\n**Total = ${v:,.2f}**"),
                "latex_sum_then_bold_total": f"## Total\n\n$${_lt(a1)} + {_lt(a2)}$$\n\n**= ${v:,.2f}**",
                "latex_boxed": f"## Total\n\n$${_lt(a1)} + {_lt(a2)} = \\boxed{{{_lt(v)}}}$$",
                "latex_boxed_no_dollar_operands": (f"## Total\n\n$${_bare(a1)} + {_bare(a2)} = \\boxed{{{_lt(v)}}}$$"),
                "bold_total_with_sum": f"**Total: ${a1:,.2f} + ${a2:,.2f} = ${v:,.2f}**",
                "history_then_final": (f"Bob's claim was first ${a1:,.2f}, then adjusted, then approved.\n\n"
                                       f"Final answer: ${v:,.2f}"),
                "paren_breakdown_after_total": (f"${v:,.2f} (Frank ${a1:,.2f} + Carol ${a2:,.2f}; "
                                                f"no March travel claims were denied)"),
                "plus_prose_after_total": (f"${v:,.2f} — Alice's March Travel approved at ${a1:,.2f} plus "
                                           f"Frank's corrected/approved ${a2:,.2f}"),
                "denied_or_withdrawn_then_sum": (f"No March Travel claims were denied or withdrawn.\n\n**Total:**\n"
                                                 f"${a1:,.2f} + ${a2:,.2f} = **${v:,.2f}**"),
                "answer_first_then_explanation": (f"**${v:,.2f}**\n\nThat is Bob's approved ${a1:,.2f} together with "
                                                  f"Eve's approved ${a2:,.2f}; nothing was denied."),
                "explain_count_after": f"${v:,.2f} reimbursed across 4 March travel claims",
            }
            for k, s in r4_pos.items():
                sc = score(s, ans)
                assert sc == 1.0, f"Neuromancer round-4 positive {k!r} should score 1.0 (seed={seed}, {size}); got {sc}"
            r4_neg = {
                "either_in_final": f"Either ${v + 100:.2f} or ${v:.2f}",
                "wrong_final_truth_in_working": (f"Working: the approved March travel claims sum to ${v:.2f}.\n\n"
                                                 f"Final answer: ${v + 100:.2f}"),
                "wrong_latex_total_truth_operand": f"$${_lt(v)} + {_lt(a1)} = \\boxed{{{_lt(round(v + a1, 2))}}}$$",
                "both_wrong_list": f"${v:.2f} and ${v + 3:.2f} are both wrong",
                "truth_negated_then_wrong": f"Not ${v:.2f}; it is ${v + 200:.2f}",
                "wrong_table_total": f"| Bob | ${v:,.2f} |\n| **Total** | **${v + 1:,.2f}** |",
            }
            for k, s in r4_neg.items():
                sc = score(s, ans)
                assert sc == 0.0, f"Neuromancer round-4 negative {k!r} should score 0.0 (seed={seed}, {size}); got {sc}"
    print("Neuromancer: round-4 final-statement assertions PASS (LaTeX/table/sum totals in; wrong finals out).")
