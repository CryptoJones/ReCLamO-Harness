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

    # Initial flags use one vocabulary
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

    # Corrections remove flags for non-culprits
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

    # Transaction logs
    for name, txns in transactions.items():
        doc_id += 1
        log = f"=== Transaction Log for {name} ===\n"
        for amt, desc, date in txns:
            log += f"{date} | {desc} | ${amt:,.2f}\n"
        log += "\n"
        parts.append(log)

    # Final summary uses different wording: double-dipped invoices, non-compliant vendor
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

    # Padding to reach target size
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

    # Shuffle everything except the final summary
    non_summary = parts[:-1]
    rng.shuffle(non_summary)
    context = "".join(non_summary + [parts[-1]])

    # Question explicitly asks for the employee and the sum of THEIR flagged expenses
    question = (
        "In the final audit summary, which employee was the only one flagged for both "
        "'double-dipped invoices' and 'non-compliant vendor', and what was the total "
        "dollar amount of all expenses in that employee’s transaction log?"
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
    text = answer_text.strip()

    # Try to parse as a Python tuple string first
    if text.startswith('(') and text.endswith(')'):
        inner = text[1:-1].strip()
        if ',' in inner:
            parts = [p.strip().strip("'\" ") for p in inner.split(',', 1)]
            if len(parts) == 2:
                candidate_name = parts[0]
                try:
                    candidate_amount = int(float(re.sub(r"[^\d.-]", "", parts[1])))
                except ValueError:
                    candidate_amount = None
                if candidate_amount is not None:
                    if (candidate_name.lower() == truth_name.lower() and
                        candidate_amount == truth_amount):
                        return 1.0

    # Natural language extraction: name must be a full person name (Title Case tokens)
    # Amount can be $123, $123.45, 123, 123.45, 1,234, 1,234.56 etc.
    name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
    amount_pattern = re.compile(
        r"(?:^|\s|[^\w])"  # non-word or start
        r"(?:\$?\s*)?"       # optional dollar sign
        r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+)"  # amount
        r"(?:[^\w]|$)"      # non-word or end
    )

    names = [n for n in name_pattern.findall(text)]
    raw_amounts = amount_pattern.findall(text)

    amounts = []
    for a in raw_amounts:
        clean = re.sub(r"[^\d.]", "", a)
        try:
            amounts.append(float(clean))
        except ValueError:
            pass

    # Check for exactly ONE name and ONE amount, both correct
    name_ok = any(n.lower() == truth_name.lower() for n in names)
    amount_ok = any(abs(a - truth_amount) < 0.01 for a in amounts)

    # If more than one distinct name or more than one distinct amount appears,
    # the answer is hedged -> score < 1.0
    distinct_names = set(n.lower() for n in names)
    distinct_amounts = set(a for a in amounts)

    if len(distinct_names) > 1 or len(distinct_amounts) > 1:
        return 0.0  # hedged or multiple candidates

    if name_ok and amount_ok:
        return 1.0
    elif name_ok or amount_ok:
        return 0.0  # partial but wrong -> 0 not 0.5
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
        assert score("Wrong Name, $0", data["answer"]) == 0.0
        assert score(f"{data['answer'][0]}, $999999", data["answer"]) == 0.0
        assert score("Someone Else, $0", data["answer"]) == 0.0
        # Hedged answers
        assert score(f"{data['answer'][0]} or Other, {data['answer'][1]}", data["answer"]) == 0.0
        assert score(f"{data['answer'][0]}, {data['answer'][1]} or 0", data["answer"]) == 0.0
        # Format variations
        assert score(f"The answer is {data['answer'][0]}; total {data['answer'][1]}", data["answer"]) == 1.0
        assert score(f"{data['answer'][0]}, ${data['answer'][1]:,}", data["answer"]) == 1.0
        assert score(f"{data['answer'][0]}, ${data['answer'][1]:,.2f}", data["answer"]) == 1.0
        assert score(f"{data['answer'][0]}, {data['answer'][1]} dollars", data["answer"]) == 1.0

    # Sweep seeds 0-4, all sizes
    for seed in range(5):
        for size in ["small", "medium", "large"]:
            d = generate(seed, size)
            n, amt = d["answer"]
            # Correct in multiple formats
            assert score(f"{n}, {amt}", d["answer"]) == 1.0
            assert score(f"{n}, ${amt:,}", d["answer"]) == 1.0
            assert score(f"Employee: {n}, total: ${amt:,.2f}", d["answer"]) == 1.0
            # Hedged / multi-candidate -> 0
            assert score(f"{n} or X, {amt}", d["answer"]) == 0.0
            assert score(f"{n}, {amt} or {amt+1}", d["answer"]) == 0.0
            # Wrong name or amount -> 0
            assert score("Wrong, 0", d["answer"]) == 0.0
            assert score(f"{n}, 0", d["answer"]) == 0.0
    print("MasterControl: all scorer assertions PASS.")
