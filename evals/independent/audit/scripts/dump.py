"""Dump small contexts/questions/keys for seeds 0-4 of every active generator."""
import importlib.util, json, sys, os

NAMES = ["Cerebex", "GLaDOS", "MasterControl", "Multivac", "Neuromancer", "SELMA", "SHODAN", "TheDixieFlatline"]


def load(src, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(src, name + ".py"))
    g = importlib.util.module_from_spec(spec)
    sys.modules[name] = g
    spec.loader.exec_module(g)
    return g


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    for name in NAMES:
        g = load(src, name)
        for seed in range(5):
            d = g.generate(seed, "small")
            open(f"{out}/{name}_s{seed}.ctx.txt", "w").write(d["context"])
            open(f"{out}/{name}_s{seed}.q.txt", "w").write(d["question"])
            json.dump({"question": d["question"], "answer": d["answer"], "answer_repr": repr(d["answer"])},
                      open(f"{out}/{name}_s{seed}.key.json", "w"), indent=1, default=str)
    print("ok")
