#!/usr/bin/env python3
"""Construct-validity check (issue #86; TEST-PLAN 1b): can a non-LLM shortcut solve the tasks?

For each of the eight generators, two deterministic answers built from the question and the
document only, no model and no answer key:

* ``last``: the **last-mentioned candidate** of the answer's type (last location named in the
  document, last person named in an assignment, last dollar amount, last status line for the
  requirement, ...). This is the "search, not reasoning" baseline.
* ``heuristic``: a slightly keener regex shortcut on the question's key terms (follow the
  asset's renames, pick the assignment mail for the named review, take the audit-summary
  line that carries both flags, sum the approved amounts for the named month and category,
  ...). Still no state tracking of amendments, reversals, delegations or custody chains.

Both are graded by the task's own pinned ``score()``, exactly as a model answer is. A
generator where either shortcut scores high measures search, not multi-hop reasoning, and
the paper says so (TEST-PLAN 1b, construct-validity check).

    uv run python evals/independent/shortcut_solver.py --seeds 4-9 --sizes small,medium
    uv run python evals/independent/shortcut_solver.py --seeds 4-43 --out runs/shortcut.md

Written from the generators' document templates and the question text. The author had seen
the seed-4 and seed-5 keys of the tasks while sampling document formats; nothing here was
tuned against a key, and seeds 10-43 are reported as a held-out check.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
SIZES = ("small", "medium", "large")

MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
QUOTED = re.compile(r"'([^']+)'")
NAME = re.compile(r"\b([A-Z][a-z]+(?:[-'][A-Z][a-z]+)? [A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)\b")


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _last(items: list, default=None):
    return items[-1] if items else default


# ------------------------------------------------------------------ TheDixieFlatline

DIXIE_LOC = re.compile(
    r"\b(Room \d{3}|The Vault|Datacenter Alpha|Datacenter Beta|Offsite Storage|"
    r"Basement Level 1|Executive Suite|The Annex|Server Room C)\b"
)


def dixie_last(question: str, doc: str) -> str:
    return _last(DIXIE_LOC.findall(doc), "")


def dixie_heuristic(question: str, doc: str) -> str:
    """Follow the asset's renames, then take the last location named in any message that
    mentions one of its names. No custody or office tracking."""
    aliases = QUOTED.findall(question)[:1]
    for cur, new in re.findall(r"'([^']+)' will now be known as '([^']+)'", doc):
        if cur in aliases and new not in aliases:
            aliases.append(new)
    best = ""
    for msg in doc.split("Message-ID:"):
        if any(f"'{a}'" in msg for a in aliases):
            loc = _last(DIXIE_LOC.findall(msg))
            if loc:
                best = loc
    return best or dixie_last(question, doc)


# ------------------------------------------------------------------------- SELMA

SELMA_ASSIGN = re.compile(
    r"(?:assigning|reassigning|handing|transferring|delegating)\b[^\n]*?"
    r"\bto ([A-Z][a-z]+ [A-Z][a-z]+)"
)
SELMA_TAKE = re.compile(
    r"([A-Z][a-z]+ [A-Z][a-z]+)\b[^\n]*?"
    r"\b(?:will take over|is taking over|now owns|is now the owner)"
)


def _selma_messages(question: str, doc: str) -> list[str]:
    m = re.search(r"the ([A-Z][\w ]+? Review)\b", question)
    topic = m.group(1) if m else "Review"
    return [msg for msg in re.split(r"(?=^From: )", doc, flags=re.M) if topic in msg]


def selma_last(question: str, doc: str) -> str:
    names = [n for msg in _selma_messages(question, doc) for n in NAME.findall(msg)]
    return _last(names, "Unassigned")


def selma_heuristic(question: str, doc: str) -> str:
    """The last message about the named review that assigns, reassigns or unassigns."""
    owner = "Unassigned"
    for msg in _selma_messages(question, doc):
        low = msg.lower()
        hit = SELMA_ASSIGN.search(msg) or SELMA_TAKE.search(msg)
        if hit:
            owner = hit.group(1)
        elif any(w in low for w in ("unassigned", "cancelled", "declined", "stepping down")):
            owner = "Unassigned"
    return owner


# ----------------------------------------------------------------- MasterControl


def _mc_logs(doc: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in re.finditer(r"=== Transaction Log for ([^=\n]+?) ===\n(.*?)(?=\n\n|\Z)", doc, re.S):
        name = m.group(1).strip()
        out[name] = out.get(name, 0.0) + sum(_money(x) for x in MONEY.findall(m.group(2)))
    return out


def _mc_summary(doc: str) -> str:
    i = doc.find("=== FINAL AUDIT SUMMARY ===")
    return doc[i:] if i >= 0 else doc


def mc_last(question: str, doc: str) -> str:
    logs = _mc_logs(doc)
    names = [n for n in NAME.findall(_mc_summary(doc)) if n in logs]
    name = _last(names, _last(sorted(logs), ""))
    return f"{name}; ${logs.get(name, 0):.0f}"


def mc_heuristic(question: str, doc: str) -> str:
    """The summary line that carries both quoted flags names the employee; the amount is
    the plain sum of that employee's transaction log (corrections ignored)."""
    flags = [f.lower() for f in QUOTED.findall(question)][:2]
    logs = _mc_logs(doc)
    name = ""
    for line in _mc_summary(doc).splitlines():
        low = line.lower()
        if all(f in low for f in flags):
            for n in logs:
                if n.lower() in low:
                    name = n
    if not name:
        hits: Counter = Counter()
        for line in _mc_summary(doc).splitlines():
            low = line.lower()
            for n in logs:
                if n.lower() in low and any(f in low for f in flags):
                    hits[n] += 1
        name = hits.most_common(1)[0][0] if hits else _last(sorted(logs), "")
    return f"{name}; ${logs.get(name, 0):.0f}"


# ---------------------------------------------------------------------- Multivac


def _multivac_req(question: str) -> str:
    m = re.search(r"\b(R\d+)\b", question)
    return m.group(1) if m else ""


def _multivac_initial(doc: str, rid: str) -> tuple[str, str]:
    m = re.search(rf"^- {re.escape(rid)}: (.*?) \(Status: ([^,)]+), Priority:", doc, re.M)
    return (m.group(1), m.group(2)) if m else ("", "")


def _multivac_status_changes(doc: str, rid: str) -> list[str]:
    return re.findall(
        rf"Requirement {re.escape(rid)} status changed from \S+(?: \S+)? to ([A-Z][a-zA-Z ]+?) \(v",
        doc,
    )


def multivac_last(question: str, doc: str) -> str:
    rid = _multivac_req(question)
    desc, status = _multivac_initial(doc, rid)
    return f"{rid}: {desc} — Status: {_last(_multivac_status_changes(doc, rid), status)}"


def multivac_heuristic(question: str, doc: str) -> str:
    """Initial description plus every clarification appended in order, last status line."""
    rid = _multivac_req(question)
    desc, status = _multivac_initial(doc, rid)
    for clar in re.findall(rf"Requirement {re.escape(rid)} updated with: (.*?) \(v\d+\)", doc):
        if f"({clar})" not in desc:
            desc = f"{desc} ({clar})"
    return f"{rid}: {desc} — Status: {_last(_multivac_status_changes(doc, rid), status)}"


# ------------------------------------------------------------------- Neuromancer

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def _neuro_terms(question: str) -> tuple[str, str]:
    month = re.search(rf"\b({MONTHS})\b", question)
    cat = re.search(r"\b(travel|meal|entertainment|lodging|equipment|training)\w*", question, re.I)
    return (month.group(1) if month else "", cat.group(1).capitalize() if cat else "")


def neuro_last(question: str, doc: str) -> str:
    return f"${_money(_last(MONEY.findall(doc), '0')):.2f}"


def neuro_heuristic(question: str, doc: str) -> str:
    """Sum of 'approved for $X' in Finance replies whose subject is the named month and
    category. Adjustments and later denials are ignored."""
    month, cat = _neuro_terms(question)
    pat = rf"Re: {month} {cat}\n[^\n]*approved for \$([\d,]+\.\d+)"
    return f"${sum(_money(x) for x in re.findall(pat, doc)):.2f}"


# ----------------------------------------------------------------------- Cerebex


def cerebex_last(question: str, doc: str) -> str:
    return f"${_money(_last(MONEY.findall(doc), '0')):.2f}"


def cerebex_heuristic(question: str, doc: str) -> str:
    """Sum of the amounts in emails that contain both the category word and 'approved'."""
    m = re.search(r"\b(travel|meals|office supplies|software licences|training)\b", question, re.I)
    cat = m.group(1).lower() if m else "travel"
    total = 0.0
    for msg in re.split(r"\n(?=From: )", doc):
        low = msg.lower()
        if cat in low and "approved" in low and "not approved" not in low and "rescind" not in low:
            total += sum(_money(x) for x in MONEY.findall(msg))
    return f"${total:.2f}"


# ------------------------------------------------------------------------ SHODAN


def _shodan_offices(question: str) -> list[str]:
    m = re.search(r"offices: ([^?]+)\?", question)
    return [o.strip() for o in m.group(1).split(",")] if m else []


def shodan_last(question: str, doc: str) -> str:
    """Per office, the last integer within 120 characters after the office's last mention."""
    offices = _shodan_offices(question)
    label = re.compile("|".join(re.escape(o) for o in offices)) if offices else None
    out = []
    for office in offices:
        i = doc.rfind(office)
        window = doc[i + len(office) : i + len(office) + 120] if i >= 0 else ""
        nxt = label.search(window) if label else None
        if nxt:
            window = window[: nxt.start()]
        nums = re.findall(r"\b(\d{1,6})\b", window)
        out.append(f"{office}: {_last(nums, '0')}")
    return "\n".join(out)


def shodan_heuristic(question: str, doc: str) -> str:
    """The most frequent candidate: every office at zero (the question says to include
    offices with zero credits, and no passage states an office total)."""
    return "\n".join(f"{office}: 0" for office in _shodan_offices(question))


# ------------------------------------------------------------------------ GLaDOS


def _certifiers(text: str) -> list[str]:
    return [n for s in re.findall(r"[^.\n]*certif[^.\n]*", text) for n in NAME.findall(s)]


def _glados_answer(cert: str, amt: str) -> str:
    return (
        f"The restated authorization passed. Certifying member: {cert}. "
        f"Net amount: ${_money(amt):,.0f}."
    )


def glados_last(question: str, doc: str) -> str:
    return _glados_answer(_last(_certifiers(doc), ""), _last(MONEY.findall(doc), "0"))


def glados_heuristic(question: str, doc: str) -> str:
    """Follow the working title through 'successor' / 'renamed' sentences, take the last
    dollar amount in a paragraph naming the latest title, and the last person named in a
    certification sentence that names it. Outcome is always 'passed'."""
    titles = QUOTED.findall(question)[:1]
    link = (
        r"'([^']+)'[^.\n]*?(?:renamed|succeeded by|successor|now known as|carried forward as)"
        r"[^.\n]*?'([^']+)'"
    )
    for a, b in re.findall(link, doc):
        if a in titles and b not in titles:
            titles.append(b)
    latest = titles[-1] if titles else ""
    paras = [p for p in doc.split("\n\n") if latest and latest in p]
    amt = _last([x for p in paras for x in MONEY.findall(p)], _last(MONEY.findall(doc), "0"))
    certs = [n for p in paras if "certif" in p.lower() for n in NAME.findall(p)]
    return _glados_answer(_last(certs, _last(_certifiers(doc), "")), amt)


SOLVERS: dict[str, dict[str, Callable[[str, str], str]]] = {
    "TheDixieFlatline": {"last": dixie_last, "heuristic": dixie_heuristic},
    "SELMA": {"last": selma_last, "heuristic": selma_heuristic},
    "MasterControl": {"last": mc_last, "heuristic": mc_heuristic},
    "Multivac": {"last": multivac_last, "heuristic": multivac_heuristic},
    "Neuromancer": {"last": neuro_last, "heuristic": neuro_heuristic},
    "Cerebex": {"last": cerebex_last, "heuristic": cerebex_heuristic},
    "SHODAN": {"last": shodan_last, "heuristic": shodan_heuristic},
    "GLaDOS": {"last": glados_last, "heuristic": glados_heuristic},
}


# ------------------------------------------------------------------------ runner


def load_generator(lane: str, manifest: dict):
    entry = manifest["generators"][lane]["active"]
    path = HERE / entry["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"{entry['file']} does not match its pinned sha256")
    spec = importlib.util.spec_from_file_location(f"shortcut_gen_{lane}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_seeds(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def evaluate(lanes: list[str], sizes: list[str], seeds: list[int], manifest: dict) -> list[dict]:
    rows = []
    for lane in lanes:
        gen = load_generator(lane, manifest)
        for size in sizes:
            for seed in seeds:
                d = gen.generate(seed, size)
                for kind, fn in SOLVERS[lane].items():
                    ans = fn(d["question"], d["context"])
                    rows.append(
                        {
                            "task": lane,
                            "size": size,
                            "seed": seed,
                            "kind": kind,
                            "score": float(gen.score(ans, d["answer"])),
                            "answer": ans[:300],
                        }
                    )
    return rows


def report(rows: list[dict], label: str) -> str:
    L = [f"# Shortcut solvers (#86): exact match by the task's own scorer ({label})", ""]
    L.append(
        "`last` = last-mentioned candidate; `heuristic` = regex shortcut on the question's "
        "key terms. No LLM, no answer key."
    )
    L += [
        "",
        "| task | size | n | last exact | last mean | heuristic exact | heuristic mean | flag |",
        "|---|---|---|---|---|---|---|---|",
    ]
    flags = []
    for task in sorted({r["task"] for r in rows}):
        for size in SIZES:
            sub = {
                k: [r for r in rows if r["task"] == task and r["size"] == size and r["kind"] == k]
                for k in ("last", "heuristic")
            }
            n = len(sub["last"])
            if not n:
                continue
            ex = {k: sum(r["score"] >= 1.0 for r in v) for k, v in sub.items()}
            mean = {k: statistics.fmean(r["score"] for r in v) for k, v in sub.items()}
            high = max(ex.values()) / n >= 0.5
            if high:
                flags.append(f"{task}/{size}")
            L.append(
                f"| {task} | {size} | {n} | {ex['last']}/{n} | {mean['last']:.2f} | "
                f"{ex['heuristic']}/{n} | {mean['heuristic']:.2f} | {'SEARCH' if high else ''} |"
            )
    L += [
        "",
        "Flag = a shortcut is exact on at least half the cells: the task measures search "
        "as much as reasoning there.",
    ]
    L.append(f"Flagged: {', '.join(flags) if flags else 'none'}.")
    L += ["", "*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seeds", default="4-9")
    ap.add_argument("--sizes", default="small,medium")
    ap.add_argument("--tasks", default=",".join(SOLVERS))
    ap.add_argument("--out", type=Path, default=None, help="markdown report")
    ap.add_argument("--json", type=Path, default=None, help="per-cell rows")
    args = ap.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = evaluate(args.tasks.split(","), args.sizes.split(","), parse_seeds(args.seeds), manifest)
    md = report(rows, f"seeds {args.seeds}, sizes {args.sizes}")
    print(md)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
