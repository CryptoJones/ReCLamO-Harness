"""Print the non-noise messages of a TheDixieFlatline context (text-only parse), sorted by Date."""
import re, sys

NOISE = {"Lunch", "Cleaning", "Outage", "Status report", "Policy update", "Distractor Asset", "Re: Move"}
txt = open(sys.argv[1]).read()
msgs = re.split(r"\n(?=Message-ID: )", txt)
rows = []
for m in msgs:
    hdr, _, body = m.partition("\n\n")
    h = dict(re.findall(r"^(\S[^:]*): (.*)$", hdr, re.M))
    subj = h.get("Subject", "")
    if subj in NOISE and "--all" not in sys.argv:
        continue
    rows.append((int(h.get("Date", "0")), h.get("Message-ID"), h.get("From"), h.get("To"), subj, body.strip()))
order = sorted(rows) if "--sort" in sys.argv else rows
for r in order:
    print(f"[{r[0]}] {r[1]} {r[2]} -> {r[3]} | {r[4]}\n    {r[5]}")
