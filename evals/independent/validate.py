"""Extract each lane's generator and validate it inside a no-network container.

Usage: python3 validate.py <answers_dir> <gen_dir>
Writes <gen_dir>/<lane>.py and <gen_dir>/report.json.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

answers, gen = Path(sys.argv[1]), Path(sys.argv[2])
gen.mkdir(exist_ok=True)

CHECK = r'''
import importlib.util, json, re, sys, time
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec); sys.modules["g"] = g
spec.loader.exec_module(g)
out = {}
for size in ("small", "medium", "large"):
    t = time.time()
    a = g.generate(0, size); b = g.generate(0, size); c = g.generate(1, size)
    truth = a["answer"]; ctx = a["context"]
    toks = [w for w in re.findall(r"[A-Za-z0-9][\w-]{2,}", str(truth))]
    out[size] = {
        "chars": len(ctx), "secs": round(time.time() - t, 2),
        "deterministic": a == b, "seed_varies": a["context"] != c["context"],
        "self_score": g.score(str(truth), truth),
        "empty_score": g.score("", truth),
        "truth_verbatim_in_context": str(truth) in ctx,
        "truth_tokens_in_context": sum(1 for w in toks if w in ctx), "truth_tokens": len(toks),
        "question": a["question"][:300], "truth": str(truth)[:300],
    }
print(json.dumps(out))
'''

report = {}
for f in sorted(answers.glob("*.md")):
    lane = f.stem
    text = f.read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    if not blocks:
        report[lane] = {"status": "no_code"}
        continue
    code = max(blocks, key=len)
    path = gen / f"{lane}.py"
    path.write_text(code)
    (gen / "_check.py").write_text(CHECK)
    cmd = [
        "docker", "run", "--rm", "--network", "none", "--memory", "2g", "--cpus", "2",
        "--read-only", "--tmpfs", "/tmp", "--user", "65534:65534",
        "-v", f"{gen.resolve()}:/g:ro", "python:3.12-slim",
    ]
    r = {}
    main = subprocess.run(cmd + ["python", "-I", f"/g/{lane}.py"], capture_output=True, text=True,
                          timeout=300)
    r["main_exit"] = main.returncode
    r["main_tail"] = (main.stdout + main.stderr)[-600:]
    try:
        chk = subprocess.run(cmd + ["python", "-I", "/g/_check.py", f"/g/{lane}.py"],
                             capture_output=True, text=True, timeout=600)
        r["check"] = json.loads(chk.stdout) if chk.returncode == 0 else chk.stderr[-800:]
    except Exception as e:  # noqa: BLE001
        r["check"] = f"error: {e}"
    report[lane] = r

(gen / "report.json").write_text(json.dumps(report, indent=2))
for lane, r in report.items():
    c = r.get("check")
    if isinstance(c, dict):
        s = c["large"]
        print(f"{lane:18} main={r['main_exit']} sizes={[c[k]['chars'] for k in c]} "
              f"det={all(c[k]['deterministic'] for k in c)} self={s['self_score']} "
              f"empty={s['empty_score']} verbatim={s['truth_verbatim_in_context']}")
    else:
        print(f"{lane:18} FAIL main={r.get('main_exit')} {str(c)[:200] if c else r}")
