import random
import re
from collections import defaultdict

def generate(seed: int, size: str) -> dict:
    rng = random.Random(seed)
    sizes = {"small": 60_000, "medium": 300_000, "large": 1_200_000}
    target_chars = sizes[size]

    employees = ["Lena Carter", "Marcus Boone", "Priya Patel", "Ethan Nguyen", "Sophia Lee"]
    rng.shuffle(employees)
    culprit = employees[0]

    transactions = defaultdict(list)
    for name in employees:
        n = rng.randint(3, 8) if name != culprit else rng.randint(5, 12)
        for _ in range(n):
            amount = rng.randint(100, 5000)
            desc = rng.choice([
                "Flight to Berlin", "Hotel stay", "Conference fees",
                "Client dinner", "Taxi fare", "Software license"
            ])
            date = f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
            transactions[name].append((amount, desc, date))

    truth_amount = sum(t[0] for t in transactions[culprit])

    parts = []
    doc_id = 0

    initial_flags = {
        employees[0]: ["duplicate receipts", "policy violation (high-risk vendor)"],
        employees[1]: ["missing receipt"],
        employees[2]: ["policy violation (high-risk vendor)"],
        employees[3]: ["duplicate receipts"],
        employees[4]: ["late submission"]
    }
    for name, flags in initial_flags.items():
        doc_id += 1
        email = (
            f"From: audit-team@corp.example\n"
            f"To: finance@corp.example\n"
            f"Subject: Initial Flag for Employee {doc_id}\n\n"
            f"Employee: {name}\n"
            f"Flags: {', '.join(flags)}\n"
            f"Please review.\n\n"
            f"---\n"
        )
        parts.append(email)

    corrections = [
        (employees[1], "missing receipt", "false positive"),
        (employees[2], "policy violation (high-risk vendor)", "resolved"),
        (employees[3], "duplicate receipts", "retracted"),
        (employees[4], "late submission", "approved with note")
    ]
    for name, flag, status in corrections:
        doc_id += 1
        email = (
            f"From: audit-lead@corp.example\n"
            f"To: finance@corp.example\n"
            f"Subject: Correction for {name}\n\n"
            f"Update: The '{flag}' flag for {name} was a {status}.\n"
            f"Adjust the audit summary accordingly.\n\n"
            f"---\n"
        )
        parts.append(email)

    for name, txns in transactions.items():
        doc_id += 1
        log = f"=== Transaction Log for {name} ===\n"
        for amt, desc, date in txns:
            log += f"{date} | {desc} | ${amt:,.2f}\n"
        log += "\n"
        parts.append(log)

    final_flags = {
        culprit: ["double-dipped invoices", "non-compliant vendor"],
        employees[1]: [],
        employees[2]: ["missing receipt"],
        employees[3]: ["late submission"],
        employees[4]: ["policy violation (low-risk vendor)"]
    }
    summary = (
        f"=== FINAL AUDIT SUMMARY ===\n"
        f"Date: 2024-12-01\n"
        f"Only one employee had multiple unresolved flags:\n"
        f"- {culprit}: 'double-dipped invoices' and 'non-compliant vendor' (see below).\n"
        f"All other employees had 0-1 flags.\n\n"
        f"Details:\n"
    )
    for name, flags in final_flags.items():
        if flags:
            summary += f"  * {name}: {', '.join(flags)}\n"
    summary += "\n---\n"
    parts.append(summary)

    current_size = sum(len(p) for p in parts)
    padding_needed = max(0, target_chars - current_size)
    if padding_needed > 0:
        padding = []
        words = [
            "agenda", "action", "items", "follow-up", "next", "steps",
            "quarterly", "budget", "review", "sync", "with", "team",
            "the", "and", "to", "of", "a", "for", "on", "is"
        ]
        while len("".join(padding)) < padding_needed:
            doc_id += 1
            lines = []
            for _ in range(rng.randint(10, 30)):
                line = " ".join(rng.choices(words, k=rng.randint(10, 20))).capitalize()
                lines.append(line)
            padding.append("\n".join(lines) + "\n\n")
        parts.append("".join(padding))

    non_summary = parts[:-1]
    rng.shuffle(non_summary)
    context = "".join(non_summary + [parts[-1]])

    question = (
        "Which employee's expense report was the only one flagged for both "
        "'double-dipped invoices' and 'non-compliant vendor' in the final audit summary, "
        "and what was the total dollar amount of that employee's flagged expenses?"
    )
    answer = (culprit, truth_amount)

    meta = {
        "culprit": culprit,
        "truth_amount": truth_amount,
        "context_length": len(context)
    }
    return {
        "context": context,
        "question": question,
        "answer": answer,
        "meta": meta
    }

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


_R4_EMPLOYEES = ("Lena Carter", "Marcus Boone", "Priya Patel", "Ethan Nguyen", "Sophia Lee")
_R4_EMPLOYEE_RX = _re4.compile(
    r"\b(?:"
    + "|".join(
        [_re4.escape(n) for n in _R4_EMPLOYEES]
        + [_re4.escape(n.split()[1] + ", " + n.split()[0]) for n in _R4_EMPLOYEES]
    )
    + r")\b",
    _re4.IGNORECASE,
)


def _r4_employees(text: str):
    """Occurrences of the five possible employees (first-last or last-first, any case)."""
    out = []
    for m in _R4_EMPLOYEE_RX.finditer(text):
        k = m.group(0).lower()
        if "," in k:
            last, first = [p.strip() for p in k.split(",", 1)]
            k = first + " " + last
        out.append((m.start(), m.end(), k))
    return out


def _r4_mc_amount(norm: str, truth_amount: int):
    """(amount_ok, amount_hedge) for the normalised answer. The authoritative amount is the
    last clean figure in the final segment, else in the whole text; an answer-first lead line
    is consulted only when the segment's figure is not the truth."""
    seg = _r4_segment(norm)
    val, cands = _r4_pick_amount(seg)
    scope = seg
    if val is None:
        val, cands = _r4_pick_amount(norm)
        scope = norm
    if val is not None and abs(val - truth_amount) >= 0.01:
        lead = _r4_lead(norm)
        lval, lcands = _r4_pick_amount(lead) if lead else (None, [])
        if lval is not None and abs(lval - truth_amount) < 0.01:
            val, cands, scope = lval, lcands, lead
    ok = val is not None and abs(val - truth_amount) < 0.01
    hedge = _r4_hedged(scope, [(a["start"], a["end"], a["value"]) for a in cands])
    return ok, hedge


def _r4_mc_name(norm: str, truth_name_low: str):
    """(name_ok, name_hedge). If the final segment names any of the five employees, the truth
    must be among them (a wrong name in the final statement is wrong even if the working
    mentioned the right one); otherwise the truth is looked for anywhere (first-last,
    last-first, any case) as before."""
    seg = _r4_segment(norm)
    names = _r4_employees(seg)
    if names and truth_name_low not in {k for _, _, k in names}:
        lead = _r4_lead(norm)
        lnames = _r4_employees(lead) if lead else []
        if lnames and truth_name_low in {k for _, _, k in lnames}:
            seg, names = lead, lnames
    if names:
        keys = {k for _, _, k in names}
        return truth_name_low in keys, _r4_hedged(seg, names)
    low = norm.lower()
    parts = truth_name_low.split()
    ok = truth_name_low in low
    if len(parts) == 2:
        ok = ok or (parts[1] + ", " + parts[0]) in low
    return ok, False


def score(answer_text: str, truth: tuple[str, int]) -> float:
    """Round-4 scorer for MasterControl: grades the FINAL STATEMENT.

    - 1.0 when the final statement names the right employee AND its authoritative amount
      (the last clean figure in the final segment: not an operand of a shown sum, not a
      parenthetical breakdown, not negated) equals the truth, with no explicit alternative
      between two names or two amounts in that segment.
    - 0.3 when the final statement hedges ("either X or Y", "$a or $b") and one half is right.
    - 0.4 when only one of the two is right.
    - 0.0 otherwise.
    Shown working (a table of line items, a sum, earlier figures) is never a penalty.
    """
    if not isinstance(answer_text, str):
        return 0.0
    truth_name, truth_amount = truth
    truth_name_low = truth_name.lower()
    text = answer_text.strip()

    # Parse stringified tuple like "('Priya Patel', 39195)".
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if "," in inner:
            parts = [p.strip().strip("'\"") for p in inner.split(",", 1)]
            if len(parts) == 2:
                candidate_name = parts[0]
                try:
                    candidate_amount = int(float(parts[1]))
                except ValueError:
                    candidate_amount = None
                if candidate_amount is not None:
                    if (candidate_name.lower() == truth_name_low and
                            candidate_amount == truth_amount):
                        return 1.0

    norm = _r4_normalize(answer_text)
    if not norm.strip():
        return 0.0
    amount_ok, amount_hedge = _r4_mc_amount(norm, truth_amount)
    name_ok, name_hedge = _r4_mc_name(norm, truth_name_low)
    any_hedge = name_hedge or amount_hedge

    if name_ok and amount_ok and not any_hedge:
        return 1.0
    if any_hedge and (name_ok or amount_ok):
        return 0.3
    if name_ok or amount_ok:
        return 0.4
    return 0.0

if __name__ == "__main__":
    for size in ["small", "medium", "large"]:
        print(f"\n=== Size: {size} ===")
        data = generate(0, size)
        print(f"Context length: {len(data['context']):,} chars")
        print(f"Question: {data['question']}")
        print(f"Truth: {data['answer']}")
        assert score(str(data["answer"]), data["answer"]) == 1.0
        assert score("Wrong Name, $0", data["answer"]) < 1.0
        assert score(f"{data['answer'][0]}, $999999", data["answer"]) < 1.0
        assert score("Someone Else, $0", data["answer"]) == 0.0

    # ----- Defect-specific regression assertions -----
    # 1) A sentence with the CORRECT full name embedded plus the CORRECT amount must get 1.0.
    #    Before the fix, the name regex was re.IGNORECASE, so the sentence's match grew to
    #    include the trailing words and "name_ok" became False -> score dropped to 0.5.
    # 2) A wrong name with the right amount must still get STRICTLY < 1 (the wrong-name half
    #    of the AND must keep failing).
    #
    # We sweep the original task across the seed x size grid the task requires (seeds 0-9,
    # all three sizes) and exercise both bug shapes on every cell. Any failure here means
    # the original defect (or a regression) is back.
    truth_name = "Priya Patel"
    truth_amount = 39195
    truth = (truth_name, truth_amount)
    in_sentence_correct = (
        f"The only employee flagged for both 'duplicate receipts' and "
        f"'policy violation (high-risk vendor)' in the final summary was {truth_name}, "
        f"with a total of ${truth_amount:,} in flagged expenses across their report."
    )
    wrong_name_right_amount = (
        f"After reviewing the report, my conclusion is that Not A Person, "
        f"had a total of ${truth_amount:,} in flagged expenses."
    )
    for seed in range(10):
        for size in ["small", "medium", "large"]:
            d = generate(seed, size)
            n, amt = d["answer"]
            sent_correct = (
                f"The only employee flagged for both 'duplicate receipts' and "
                f"'policy violation (high-risk vendor)' in the final summary was {n}, "
                f"with a total of ${amt:,} in flagged expenses across their report."
            )
            wrong_sent = (
                f"After reviewing the report, my conclusion is that Totally Different Person, "
                f"had a total of ${amt:,} in flagged expenses."
            )
            assert score(sent_correct, d["answer"]) == 1.0, (
                f"name-in-sentence + right amount must score 1.0 "
                f"(seed={seed}, size={size}); got {score(sent_correct, d['answer'])}"
            )
            assert score(wrong_sent, d["answer"]) < 1.0, (
                f"wrong name + right amount must score < 1 "
                f"(seed={seed}, size={size}); got {score(wrong_sent, d['answer'])}"
            )
    print("MasterControl: defect-specific assertions PASS (sentence+name works; wrong name fails).")

    # ----- TASK2 regression: raw / unformatted amount must score 1.0 -----
    # The amount regex used to use `\d{1,3}` for its first digit run, which truncated an
    # unformatted amount to its first three digits. "39195" thus matched as "391" and "95";
    # neither parses to the truth_amount, so a fully-correct plain-text answer scored 0.5.
    # After the fix the regex uses `\d+`, which reads the entire digit run as one capture
    # AND still accepts the comma-formatted variant (`\d+(?:,\d{3})*` greedily reads
    # "39,195" as one match) and the cents variant (`(?:\.\d{2})?`).
    #
    # For TRUTH = ('Priya Patel', 39195) the TASK requires ALL of the following:
    #   "The answer is Priya Patel; total 39195."            -> 1.0   (raw / unformatted)
    #   "Priya Patel was the only employee flagged, $39,195." -> 1.0   (comma-formatted)
    #   "Priya Patel, $39195.00"                              -> 1.0   (cents, no comma)
    #   "Someone Else, $39,195"                               -> < 1.0 (wrong name)
    #   "Priya Patel, $39,000"                                -> < 1.0 (wrong amount)
    #
    # We verify the SAME contract across several seeds (so the answer/name/amount come
    # out of generate() itself, not from a fixed hard-coded example). For each seed we
    # build all three positive surfaces and both negative surfaces from the cell's own
    # truth, then assert. A failure on any cell means the amount regex regressed.
    for seed in range(10):
        d = generate(seed, "medium")
        n, amt = d["answer"]
        # Positive surfaces (must score 1.0):
        raw_amount_sentence = f"The answer is {n}; total {amt}."
        formatted_amount_sentence = (
            f"{n} was the only employee flagged, ${amt:,}."
        )
        cents_no_comma = f"{n}, ${amt}.00"
        # Negative surfaces (must score strictly < 1.0):
        wrong_name_right_amt = f"Someone Else, ${amt:,}"
        right_name_wrong_amt = f"{n}, ${amt - 100:,}"

        assert score(raw_amount_sentence, d["answer"]) == 1.0, (
            f"raw amount sentence must score 1.0 (seed={seed}); "
            f"got {score(raw_amount_sentence, d['answer'])}"
        )
        assert score(formatted_amount_sentence, d["answer"]) == 1.0, (
            f"comma-formatted amount sentence must score 1.0 (seed={seed}); "
            f"got {score(formatted_amount_sentence, d['answer'])}"
        )
        assert score(cents_no_comma, d["answer"]) == 1.0, (
            f"cents-without-comma amount must score 1.0 (seed={seed}); "
            f"got {score(cents_no_comma, d['answer'])}"
        )
        assert score(wrong_name_right_amt, d["answer"]) < 1.0, (
            f"wrong name + right amount must score < 1 (seed={seed}); "
            f"got {score(wrong_name_right_amt, d['answer'])}"
        )
        assert score(right_name_wrong_amt, d["answer"]) < 1.0, (
            f"right name + wrong amount must score < 1 (seed={seed}); "
            f"got {score(right_name_wrong_amt, d['answer'])}"
        )
    print("MasterControl: raw/unformatted-amount assertions PASS "
          "(name + plain total = 1.0; wrong name or wrong amount < 1.0).")

    # ----- Scorer regression: formats and hedges -----
    emps = ["Lena Carter", "Marcus Boone", "Priya Patel", "Ethan Nguyen", "Sophia Lee"]
    for seed in range(5):
        d = generate(seed, "small")
        n, amt = d["answer"]
        other = [e for e in emps if e != n][0]
        positives = {
            "str_tuple": str(d["answer"]),
            "sentence_comma": f"{n} had total flagged expenses of ${amt:,}.",
            "sentence_bare": f"{n} had total flagged expenses of {amt}.",
            "sentence_no_comma": f"{n} had total flagged expenses of ${amt}.",
            "sentence_cents": f"{n} had total flagged expenses of ${amt}.00.",
            "sentence_usd": f"{n} had total flagged expenses of ${amt:,}.00 USD.",
            "bold": f"**{n}** — **${amt:,}**",
            "json": f'{{"employee": "{n}", "total": {amt}}}',
            "bullets": f"- Employee: {n}\n- Total flagged: ${amt:,}",
            "lowercase": f"{n.lower()}, ${amt:,}",
            "uppercase": f"{n.upper()}: ${amt:,}",
            "last_first": f"{n.split()[-1]}, {n.split()[0]} — ${amt:,}",
            "dollars_word": f"{n}; {amt:,} dollars",
            "explanation_with_other_numbers":
                f"{n} had 3 flagged reports in Q4 2024 totaling ${amt:,}.",
            "trailing_period": f"{n}, ${amt:,}.",
            "sentence_question": f"The only flagged employee is {n} with ${amt:,}.",
        }
        for k, s in positives.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, (
                f"MasterControl positive {k!r} should score 1.0 (seed={seed}); got {sc}"
            )
        # Hedged forms must score < 1.0.
        hedges = {
            "shotgun_names": f"Either {other} or {n}; ${amt:,}",
            "shotgun_amounts": f"{n}; ${amt - 1000:,} or ${amt:,}",
        }
        for k, s in hedges.items():
            sc = score(s, d["answer"])
            assert sc < 1.0, (
                f"MasterControl hedge {k!r} should score < 1.0 (seed={seed}); got {sc}"
            )
    print("MasterControl: scorer regression battery PASS (formats in/hedges out).")

    # ----- Round 4 (issue #95): final-statement scoring -----
    # Shown working is not a hedge any more: a table of line items ending in a total row, a
    # LaTeX sum, a parenthetical breakdown after the total, or a history paragraph before the
    # final answer all score 1.0 when the final statement is right. A wrong final statement
    # stays wrong even when the working mentioned the right value, and "either A or B" in the
    # final segment is a hedge.
    def _lt(v):
        return ("\\$%s" % format(v, ",")).replace(",", "{,}")

    for seed in range(5):
        d = generate(seed, "small")
        n, amt = d["answer"]
        other = [e for e in emps if e != n][0]
        a1, a2 = amt - 1234, 1234
        r4_pos = {
            "table_total_row": (
                f"The employee is **{n}**.\n\n| Date | Item | Amount |\n|------|------|--------|\n"
                f"| 2024-03-01 | Hotel stay | ${a1:,}.00 |\n| 2024-04-02 | Taxi fare | ${a2:,}.00 |\n"
                f"| **Total** | | **${amt:,}.00** |"
            ),
            "table_then_total_line_and_note": (
                f"**{n}**\n\n| Date | Item | Amount |\n|---|---|---|\n| 2024-03-01 | Hotel stay | ${a1:,}.00 |\n"
                f"| 2024-04-02 | Taxi fare | ${a2:,}.00 |\n\n**Total: ${amt:,}.00**\n\n"
                f"Note: the flags are applied at the report level, so the total covers all of {n}'s expenses."
            ),
            "latex_sum_then_bold_total": f"{n}\n\n## Total\n\n$${_lt(a1)}.00 + {_lt(a2)}.00$$\n\n**= ${amt:,}.00**",
            "latex_boxed": f"{n}\n\n## Total\n\n$${_lt(a1)}.00 + {_lt(a2)}.00 = \\boxed{{{_lt(amt)}.00}}$$",
            "boxed_plain": f"{n}: \\boxed{{\\${amt:,}}}",
            "history_then_final": (
                f"{n} was initially flagged at ${a1:,}; after the correction email the figure was revised.\n\n"
                f"Final answer: {n}, ${amt:,}"
            ),
            "paren_breakdown_after_total": f"{n} — ${amt:,}.00 (sum of 2 transactions: ${a1:,} + ${a2:,})",
            "plus_breakdown_no_parens": f"{n}; total flagged expenses = ${amt:,}.00: ${a1:,} plus ${a2:,}",
            "caveat_with_or_single_amount": (
                f"{n}\n\n**Total: ${amt:,}.00**\n\nThe document does not say whether the flags apply to the "
                f"'double-dipped invoices' or the 'non-compliant vendor' items."
            ),
            "answer_first_then_explanation": (
                f"**{n} — ${amt:,}.00**\n\nThe flags were applied to the whole report; the 'late submission' "
                f"flag for {other} was retracted."
            ),
            "lowercase_table": f"{n.lower()}\n\n| item | amount |\n|---|---|\n| hotel | ${a1:,} |\n| total | ${amt:,} |",
        }
        for k, s in r4_pos.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, f"MasterControl round-4 positive {k!r} should score 1.0 (seed={seed}); got {sc}"
        r4_neg = {
            "either_names_in_final": (f"Working: candidates are {n} and {other}.\n\n"
                                      f"Final answer: either {other} or {n}; ${amt:,}", 0.3),
            "either_amounts_in_final": (f"{n}\n\nFinal answer: ${a1:,} or ${amt:,}", 0.3),
            "wrong_name_final_right_in_working": (f"I first considered {n} (${amt:,}).\n\n"
                                                  f"Final answer: {other}, ${amt:,}", 0.4),
            "wrong_amount_final_right_in_working": (f"{n}'s log sums to ${amt:,} before corrections.\n\n"
                                                    f"Final answer: {n}, ${amt + 500:,}", 0.4),
            "truth_then_wrong_same_sentence": (f"{n}: I first got ${amt:,} but the final total is ${amt + 250:,}.", 0.4),
            "wrong_table_total": (f"{n}\n\n| Item | Amount |\n|---|---|\n| Hotel | ${amt:,}.00 |\n"
                                  f"| **Total** | **${amt + 1:,}.00** |", 0.4),
        }
        for k, (s, want) in r4_neg.items():
            sc = score(s, d["answer"])
            assert sc == want, f"MasterControl round-4 negative {k!r} should score {want} (seed={seed}); got {sc}"
    print("MasterControl: round-4 final-statement assertions PASS (working is not a hedge; wrong finals stay wrong).")
