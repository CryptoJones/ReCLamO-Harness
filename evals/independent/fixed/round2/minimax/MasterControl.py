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
        "Which employee’s expense report was the only one flagged for both "
        "'duplicate receipts' and 'policy violation (high-risk vendor)' in the final audit summary, "
        "and what was the total amount of their flagged expenses?"
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

def score(answer_text: str, truth: tuple[str, int]) -> float:
    truth_name, truth_amount = truth
    # Handle stringified tuple like "('Priya Patel', 39195)" or natural text
    text = answer_text.strip()

    # Parse stringified tuple
    if text.startswith('(') and text.endswith(')'):
        inner = text[1:-1].strip()
        if ',' in inner:
            parts = [p.strip().strip("'\"") for p in inner.split(',', 1)]
            if len(parts) == 2:
                candidate_name = parts[0]
                try:
                    candidate_amount = int(float(parts[1]))
                except ValueError:
                    candidate_amount = None
                if candidate_amount is not None:
                    if (candidate_name.lower() == truth_name.lower() and
                        candidate_amount == truth_amount):
                        return 1.0

    # Parse natural text: look for name and amount.
    # NOTE 1: The name regex must be CASE-SENSITIVE. With re.IGNORECASE, a sentence such as
    # "Priya Patel was the only employee flagged..." would have been matched as ONE giant
    # "name" string ("Priya Patel was the only employee flagged"), and so a fully-correct
    # answer (right name + right amount embedded in a sentence) would have gotten only 0.5
    # -- because the captured "name" no longer equalled the truth name string.
    # NOTE 2: The amount regex must capture the WHOLE digit run. The earlier `\d{1,3}`
    # truncated an unformatted amount to its first three digits -- "39195" came out as
    # "391" and "95" instead of "39195" -- so a fully-correct plain-text answer like
    # "The answer is Priya Patel; total 39195." scored 0.5. Switching `\d{1,3}` to `\d+`
    # keeps the comma-formatted path intact (`\d+(?:,\d{3})*` reads "39,195" as one match
    # when the source uses comma separators) AND now reads unformatted totals intact too.
    name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
    amount_pattern = re.compile(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)")

    names = name_pattern.findall(answer_text)
    amounts = amount_pattern.findall(answer_text)

    name_ok = any(truth_name.lower() == n.lower() for n in names)
    amount_ok = False
    for a in amounts:
        try:
            parsed = float(re.sub(r"[^\d.]", "", a))
            if abs(parsed - truth_amount) < 0.01:
                amount_ok = True
                break
        except ValueError:
            continue

    if name_ok and amount_ok:
        return 1.0
    elif name_ok or amount_ok:
        return 0.5
    else:
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
