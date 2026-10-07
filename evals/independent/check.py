"""Validate generators the same way the independent validator does (minus Docker).

Usage: python3 check.py fixed/Cerebex.py [more.py ...]
Checks: own __main__ self-test passes; sizes ~60K/300K/1.2M (+-25%); deterministic within and
ACROSS processes (different PYTHONHASHSEED); seed varies output; score(truth)==1; score("")<1.
"""
import json, os, subprocess, sys

TARGET = {"small": 60_000, "medium": 300_000, "large": 1_200_000}
PROBE = r'''
import hashlib, importlib.util, json, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec); sys.modules["g"] = g; spec.loader.exec_module(g)
out = {}
for s in ("small", "medium", "large"):
    a = g.generate(0, s); b = g.generate(0, s); c = g.generate(1, s)
    out[s] = {"chars": len(a["context"]), "same": a == b, "varies": a["context"] != c["context"],
              "self": g.score(str(a["answer"]), a["answer"]), "empty": g.score("", a["answer"]),
              "hash": hashlib.sha256(json.dumps([a["context"], a["question"], str(a["answer"])]).encode()).hexdigest(),
              "truth": str(a["answer"])[:120]}
print(json.dumps(out))
'''
ok_all = True
for path in sys.argv[1:]:
    problems = []
    main = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, timeout=600)
    if main.returncode != 0:
        problems.append("own __main__ self-test failed: " + (main.stderr.strip().splitlines() or ["?"])[-1])
    runs = []
    for seed in ("1", "2"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        p = subprocess.run([sys.executable, "-c", PROBE, path], capture_output=True, text=True, env=env, timeout=600)
        if p.returncode != 0:
            problems.append("probe crashed: " + p.stderr.strip()[-300:]); break
        runs.append(json.loads(p.stdout))
    if len(runs) == 2:
        r = runs[0]
        for s, tgt in TARGET.items():
            if not 0.75 * tgt <= r[s]["chars"] <= 1.25 * tgt:
                problems.append(f"{s}: {r[s]['chars']} chars, want ~{tgt}")
            if not r[s]["same"]: problems.append(f"{s}: not deterministic within a process")
            if r[s]["hash"] != runs[1][s]["hash"]: problems.append(f"{s}: differs across processes (PYTHONHASHSEED)")
            if not r[s]["varies"]: problems.append(f"{s}: seed does not change output")
            if r[s]["self"] != 1.0: problems.append(f"{s}: score(str(truth)) = {r[s]['self']}")
            if r[s]["empty"] >= 1.0: problems.append(f"{s}: empty answer scores 1.0")
        print(path, "truths:", {s: r[s]["truth"] for s in TARGET})
    print(("PASS " if not problems else "FAIL ") + path)
    for x in problems: print("   -", x)
    ok_all &= not problems
sys.exit(0 if ok_all else 1)
