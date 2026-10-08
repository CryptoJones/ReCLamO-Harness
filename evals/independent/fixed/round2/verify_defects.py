"""Independent check that the round-2 defects are gone (seeds 0-9, all sizes)."""
import importlib.util, re, sys
def load(p):
    s = importlib.util.spec_from_file_location("g" + str(abs(hash(p))), p); m = importlib.util.module_from_spec(s); sys.modules[s.name] = m; s.loader.exec_module(m); return m
which, path = sys.argv[1], sys.argv[2]; g = load(path); bad = []
for seed in range(10):
    for size in ("small", "medium", "large"):
        d = g.generate(seed, size); ctx, q, t = d["context"], d["question"], d["answer"]
        if which == "Dixie":
            if str(t) not in ctx: bad.append((seed, size, "truth not in context", t))
        elif which == "SELMA":
            if t == "Unassigned":
                if not re.search(r"unassigned|no longer responsible", ctx, re.I): bad.append((seed, size, "Unassigned w/o email"))
            elif str(t) not in ctx: bad.append((seed, size, "name not in context", t))
        elif which == "Multivac":
            qid = re.search(r"\bR\d+\b", q).group(0); aid = t["req_id"] if isinstance(t, dict) else None
            # answer must be the asked req or a req whose description says it incorporates the asked one
            desc = t.get("description", "") if isinstance(t, dict) else ""
            if aid != qid and not re.search(rf"\b{qid}\b", desc) and qid not in ctx: bad.append((seed, size, qid, aid))
            lineage_ok = aid == qid or re.search(rf"\b{qid}\b", ctx)
            if not lineage_ok: bad.append((seed, size, "asked req absent", qid))
        elif which == "MasterControl":
            name, amt = t
            for good in (f"{name} was the only employee flagged for both issues, with ${amt:,} flagged.", f"The answer is {name}; total {amt}."):
                if g.score(good, t) != 1.0: bad.append((seed, size, "good scored", g.score(good, t), good))
            if g.score(f"Someone Else was flagged, ${amt:,}", t) >= 1.0: bad.append((seed, size, "wrong name scored 1"))
print(which, "OK" if not bad else f"{len(bad)} problems: {bad[:4]}")
