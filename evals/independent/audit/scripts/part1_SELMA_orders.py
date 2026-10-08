"""SELMA: solve from TEXT by document order and by Date-header order; compare to key over many seeds.

Usage: python3 -I part1_SELMA_orders.py <active_dir> [n_seeds] [size]
Text parser only reads the context; the generator is used only to produce context + key.
"""
import importlib.util, os, re, sys
from datetime import datetime

src = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 200; size = sys.argv[3] if len(sys.argv) > 3 else "small"
spec = importlib.util.spec_from_file_location("SELMA", os.path.join(src, "SELMA.py"))
g = importlib.util.module_from_spec(spec); sys.modules["SELMA"] = g; spec.loader.exec_module(g)

EMAIL = re.compile(r"From: .*?\nTo: .*?\nDate: (?P<date>[^\n]+)\nSubject: (?P<subj>[^\n]+)\n\n(?P<body>.*?)(?=\nFrom: |\Z)", re.S)


def events(ctx):
    out = []
    for k, m in enumerate(EMAIL.finditer(ctx)):
        b = m["body"]; s = m["subj"]
        try:
            d = datetime.strptime(m["date"].strip(), "%B %d, %Y")
        except ValueError:
            d = None
        ev = None
        if mm := re.search(r"Review for Project \w+ to (\w+ \w+) from", b):
            ev = mm.group(1)
        elif mm := re.search(r"Effective immediately, (\w+ \w+) from \w[\w ]* will be taking over", b):
            ev = mm.group(1)
        elif mm := re.search(r"while (\w+ \w+) remains the lead", b):
            ev = mm.group(1)
        elif mm := re.search(r"(\w+ \w+) from [\w ]+ remains the lead", b) or re.search(r"\. (\w+ \w+) remains the lead", b):
            ev = mm.group(1)
        elif "position is unassigned" in b or "position is now unassigned" in b or "lead position is now unassigned" in b:
            ev = "Unassigned"
        elif "Delegation:" in s or "Note: AI Ethics" in s:
            ev = None  # non-ownership by generator design (delegate/note never in timeline anyway)
        if ev:
            out.append((k, d, ev))
    return out


def final(evs):
    return evs[-1][2] if evs else "Unassigned"


stats = {"n": 0, "doc_eq_key": 0, "date_eq_key": 0, "doc_ne_date": 0, "key_unassigned": 0, "header_out_of_order": 0}
bad = []
for seed in range(n):
    d = g.generate(seed, size)
    evs = events(d["context"])
    doc = final(evs)
    by_date = final(sorted(evs, key=lambda e: (e[1], e[0])))
    key = d["answer"]
    stats["n"] += 1
    stats["doc_eq_key"] += doc == key
    stats["date_eq_key"] += by_date == key
    stats["key_unassigned"] += key == "Unassigned"
    if doc != by_date:
        stats["doc_ne_date"] += 1
        bad.append((seed, key, doc, by_date))
    dates = [e[1] for e in evs]
    stats["header_out_of_order"] += any(a > b for a, b in zip(dates, dates[1:]))
print(stats)
print("first disagreements (seed, key, doc-order, date-order):", bad[:15])
