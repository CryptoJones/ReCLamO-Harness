"""Capture Cerebex.generate() internals (div_of, reports, deputy) via a profile hook.

Usage: python3 -I part1_Cerebex_trace.py <path/to/Cerebex.py> [size] [n_seeds]
"""
import importlib.util, sys, json

path = sys.argv[1]
size = sys.argv[2] if len(sys.argv) > 2 else "small"
n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
spec = importlib.util.spec_from_file_location("cb", path)
g = importlib.util.module_from_spec(spec); sys.modules["cb"] = g; spec.loader.exec_module(g)

cap = {}
def prof(frame, event, arg):
    if event == "return" and frame.f_code.co_name == "generate":
        cap.update(frame.f_locals)
summary = []
for seed in range(n):
    cap.clear()
    sys.setprofile(prof); d = g.generate(seed, size); sys.setprofile(None)
    div_of, mgrs, emp_of = cap["div_of"], cap["mgrs"], cap["emp_of"]
    ops = [m for m in mgrs if div_of[m] == "Operations"]
    deputy = cap["deputy"]
    ctx = d["context"]
    rows = []
    for r in cap["reports"]:
        if r["cat"] == "travel":
            rows.append(dict(emp=r["emp"], city=r["city"], approver=r["approver"],
                             approver_div=div_of[r["approver"]], approved=r["approved"], amt=r["amt"],
                             via_deputy=(r["approver"] == deputy)))
    hidden_city_refs = []
    for r in cap["reports"]:
        if r["cat"] != "travel":
            tag = f"{r['emp'].split()[0]}'s {r['city']} paperwork"
            if tag in ctx:
                hidden_city_refs.append(tag + f" (actually {r['cat']})")
    ops_travel = [r for r in cap["reports"] if r["cat"] == "travel" and div_of[r["approver"]] == "Operations"]
    summary.append(dict(
        seed=seed, size=size, truth=d["answer"], ops_mgrs=ops, deputy=deputy, deputy_div=div_of.get(deputy),
        delegator_reports=[e for e, m in emp_of.items() if ops and m == ops[0]],
        division_word_in_ctx={dv: (dv in ctx) for dv in g.DIVISIONS},
        travel_reports=rows, n_ops_travel=len(ops_travel),
        n_ops_travel_approved=sum(r["approved"] for r in ops_travel),
        decision_refs_to_nontravel=hidden_city_refs))
print(json.dumps(summary, indent=1, default=str))
