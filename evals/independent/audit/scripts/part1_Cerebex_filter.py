"""Print the non-noise messages of a Cerebex context (text-only reading aid)."""
import re, sys

NOISE = ("Printer / badge", "parking situation", "Team lunch", "Merged: agenda", "Standup notes", "Flights to")
t = open(sys.argv[1]).read()
for i, m in enumerate(re.split(r"\n\n\n(?=From: )", t)):
    lines = m.split("\n")
    if len(lines) > 3 and any(n in lines[3] for n in NOISE):
        continue
    print("#%d" % i, m.strip().replace("\n\n", "\n"))
    print()
