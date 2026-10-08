"""Dump #22 rows scoring < 1 (any size) with truth + answer, and rescore with current active scorers.

Usage: python3 -I rescore_rows.py <active_dir> <rows.json> [<rows.json> ...]
Read-only. Prints one block per non-exact row.
"""
import importlib.util, json, os, sys

def load(src, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(src, name + ".py"))
    g = importlib.util.module_from_spec(spec); sys.modules[name] = g; spec.loader.exec_module(g); return g

src = sys.argv[1]
mods = {}
for path in sys.argv[2:]:
    rows = json.load(open(path))["rows"]
    print(f"######## {path}  ({len(rows)} rows)")
    for r in rows:
        if r.get("score") is None or r.get("error"):
            if r.get("error"):
                print(f"-- {r['task']} {r['size']} {r['mode']} s{r['seed']} ERROR {str(r['error'])[:100]}")
            continue
        if r["score"] >= 1:
            continue
        t = r["task"]
        g = mods.setdefault(t, load(src, t))
        truth = r["truth"]
        if t == "MasterControl" and isinstance(truth, list):
            truth = tuple(truth)
        try:
            now = g.score(r["answer"] or "", truth)
        except Exception as e:
            now = f"ERR {e}"
        ans = (r["answer"] or "").replace("\n", " \\n ")
        print(f"-- {t} {r['size']} {r['mode']} s{r['seed']} score={r['score']} rescore_now={now}\n   truth={json.dumps(truth)[:300]}\n   answer={ans[:600]}")
