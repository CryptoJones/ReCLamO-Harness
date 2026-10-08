import importlib.util, sys, random
p="/Users/akclark/source/repos/ReCLamO-Harness/evals/independent/fixed/active/Neuromancer.py"
spec=importlib.util.spec_from_file_location("n",p); n=importlib.util.module_from_spec(spec); spec.loader.exec_module(n)
src=open(p).read()
# re-run the data part to inspect entries: patch to capture
for seed in (0,1):
    ns={}
    code=src.split("    # ---------- Text generation")[0]+"    return entries\n"
    exec(code,ns)
    for e in ns["generate"](seed,"small"):
        if e["category"]=="Travel" and e["month"]=="March" or (e["employee"]=="Hank" and e["category"]=="Travel"):
            print(seed,e)
    d=n.generate(seed,"small"); print(seed,"len",len(d["context"]), d["meta"])
