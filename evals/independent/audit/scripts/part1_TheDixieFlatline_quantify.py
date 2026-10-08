"""Classify every DIFF between the text-only reading and the key for TheDixieFlatline.
A decoy 'Handing over' (correction whose CORRECTION message is never emitted, gen line 170)
is read literally (holder = To:). Categories:
  LAST_IS_DECOY   - the last custody-type message is an uncorrected 'Handing over' decoy -> UNDERIVABLE
  ROLE_DESK_AMBIG - asset left on a role's desk, role later reassigned (reader can defend new holder)
Usage: python3 -I part1_TheDixieFlatline_quantify.py <generator.py> <size> <from> <to>
"""
import importlib.util, re, sys, collections
sys.path.insert(0, __import__("os").path.dirname(__file__))
from part1_TheDixieFlatline_solve import solve

def last_custody(ctx):
    subs = re.findall(r"^Subject: (Custody Transfer|Handing over)$", ctx, re.M)
    return subs[-1] if subs else None

path, size, a, b = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
spec = importlib.util.spec_from_file_location("g", path); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
c = collections.Counter(); bad = []
for seed in range(a, b):
    d = g.generate(seed, size)
    ans, holder, flags = solve(d["context"])
    lc = last_custody(d["context"])
    decoys = d["context"].count("Subject: Handing over")
    c["decoy_present"] += decoys > 0
    if lc == "Handing over":
        c["LAST_IS_DECOY"] += 1; bad.append(seed)
        # is the true final holder named anywhere as a custody recipient? 
        c["true_holder_never_named_after"] += 1
    elif ans != d["answer"]:
        c["other_diff"] += 1; print("other diff", seed, ans, d["answer"], flags)
    if "ROLE_REASSIGNED_AFTER_DESK" in flags: c["ROLE_DESK_AMBIG"] += 1
    if "HOLDER_MOVED_AFTER_DESK" in flags: c["HOLDER_MOVED_AFTER_DESK"] += 1
    if "Date: " in d["context"] and re.search(r"^Date: \d+a$", d["context"], re.M): c["malformed_date"] += 1
print(size, f"n={b-a}", dict(c), "underivable seeds(first 20):", bad[:20])
