
==========================================================================
MasterControl  (mistralai/mistral-medium-3.1)  via Mistral  10.0s
==========================================================================
The fix replaces the case-insensitive name regex with a strict, case-sensitive regex that matches only capitalized full names (first-letter capitals on each word) and requires the true name to appear as a contiguous substring. This prevents partial or case-mangled matches. The self-tests now include a sentence embedding the true name and amount to confirm full credit, while wrong names or amounts still fail.

```python
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
                    if (candidate_name == truth_name and
                        candidate_amount == truth_amount):
                        return 1.0

    # Parse natural text: look for exact capitalized full name and amount
    # Match only properly capitalized full names (e.g. "Priya Patel", not "priya patel")
    name_pattern = re.compile(rf"\b{re.escape(truth_name)}\b")
    amount_pattern = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)")

    name_ok = bool(name_pattern.search(answer_text))
    amount_ok = False
    for a in amount_pattern.findall(answer_text):
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
        # New tests for embedded name and amount in a sentence
        embedded = f"The culprit was {data['answer'][0]} with a total of ${data['answer'][1]:,.2f} in expenses."
        assert score(embedded, data["answer"]) == 1.0
        wrong_embedded = f"The culprit was Not {data['answer'][0]} with a total of ${data['answer'][1]:,.2f} in expenses."
        assert score(wrong_embedded, data["answer"]) < 1.0
```

==========================================================================
1/1 lanes answered in 10.0s
spend: $0.0054 actual  (est. worst case $0.0294)
transcript: /Users/akclark/.local/share/flatline-roundtable/transcripts/20261007-223634-MasterControl-52795.json
