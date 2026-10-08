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

# Revision request (round 2)

The generator below is the version of your task currently used for evaluation. A real evaluation run found this defect in it:

**The scorer rejects a correct name written inside a sentence: the name regex runs with IGNORECASE, so 'Priya Patel was the only employee flagged...' matches as one long 'name' and a correct answer scores 0.5. Fix score() so a correct full name anywhere in a sentence gets full name credit (e.g. case-sensitive capitalised-name matching, or checking whether the true name occurs as a phrase), while wrong names still fail. Add self-test cases: the name embedded in a sentence plus the right amount scores 1.0; a different name plus the right amount scores < 1.**

Return a corrected version that still satisfies the whole brief (sizes ~60K/300K/1.2M, deterministic across processes, standard library only, Python 3.11 compatible: no backslashes inside f-string expressions). Keep the same task idea, question style and difficulty; change only what the defect requires. Same deliverable format: one paragraph (mention what you changed) then the single complete ```python block.

## Current generator

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

    # Parse natural text: look for name and amount
    name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", re.IGNORECASE)
    amount_pattern = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)")

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

```
