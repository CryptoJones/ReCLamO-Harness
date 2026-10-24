#!/usr/bin/env python3
"""H1 analysis for the paper (issue #85; TEST-PLAN 1b "Analysis specification", 1d decision 9).

Standard library only, like ``make_tables.py``. Reads the per-arm row files that
``evals/independent/run_eval.py`` writes and produces, per input size, for the paired
comparison harness v0.1 32K vs plain-128K:

* the pre-registered primary (every pair counts; an arm with no answer is wrong): exact
  McNemar on the discordant pairs, z = (b - c) / sqrt(b + c), with the O'Brien-Fleming
  boundary for the look;
* a task-clustered paired bootstrap (resample tasks, then pairs within task) for the
  difference in exact-match rate and in mean score;
* a GLMM: logit, arm fixed effect, task random intercept, fitted by maximum likelihood
  with Gauss-Hermite quadrature (pure Python); Wald z and p for the arm effect;
* leave-one-task-out estimates;
* the minimum detectable effect at each look's n, from the observed discordance rate;
* the labelled exclusion sets of decision 9: secondary (plain ``does_not_fit`` pairs
  dropped), and sensitivity-only sets (plain ``length`` dropped; harness
  ``max_iterations``/``timeout`` dropped; both arms finished);
* completion rate per arm, cost and latency per arm (seconds p50/p95, prompt and
  completion tokens, sub-calls, turns), and a failure taxonomy from ``stop_reason``;
* breakdowns per task, per generator author (vendor / model), and per evidence position
  (where the answer's last literal mention sits in the context: first / middle / last
  third, or "computed" when the answer is a derived value that never appears verbatim);
* the A/A noise floor: plain-32K vs plain-128K at small on cells where both fit.

Seeds 2-3 are exploratory and excluded unless ``--seeds`` says otherwise; the
confirmatory set is seeds 4 onward (TEST-PLAN 1b).

    python3 paper/analysis/h1_analysis.py --runs runs/exp-v02/rescored-round4 \\
        --aa-runs runs/exp-v02 --look 3 --out paper/tables --report runs/h1-analysis.md

``--look`` picks the boundary: 1 -> 3.471, 2 -> 2.454, 3 -> 2.004. Nothing here reads
confirmatory rows until it is run on them; the tests use a synthetic fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import statistics
import sys
from collections import Counter, OrderedDict
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
INDEP = REPO / "evals" / "independent"

HARNESS = "h-v01-32k"
PLAIN = "plain-131k"
PLAIN_SMALL = "plain-32k"
SIZES = ("small", "medium")
CONFIRMATORY_FROM = 4
BOUNDARIES = {1: 3.471, 2: 2.454, 3: 2.004}  # O'Brien-Fleming, K=3, two-sided alpha .05
LOOK_PAIRS = {1: 112, 2: 216, 3: 320}
Z_BETA_80 = 0.8416212  # 80% power
BOOT = 10_000
RNG_SEED = 20261023

ANSWERED = {"final", "final_var", "answer_dict", "stop"}
FORCED = {
    "max_iterations": "forced finish: turn cap",
    "timeout": "forced finish: time limit",
    "error_limit": "forced finish: error limit",
    "context_overflow": "forced finish: context overflow",
}


# --------------------------------------------------------------------------- rows


def score(r: dict) -> float:
    return float(r.get("score") or 0.0)


def exact(r: dict) -> bool:
    return score(r) >= 1.0


def seed_of(r: dict) -> int:
    return int(r["seed"])


def load_rows(path: Path, seeds: set[int] | None) -> list[dict]:
    """One row per (task, size, seed); the last written wins (resumed runs append)."""
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    cells: dict[tuple, dict] = {}
    for r in rows:
        if seeds is None or seed_of(r) in seeds:
            cells[(r["task"], r["size"], seed_of(r))] = r
    return list(cells.values())


def taxonomy(r: dict) -> str:
    s = r.get("stop_reason")
    if r.get("does_not_fit") or s == "does_not_fit":
        return "not_run: does_not_fit"
    if r.get("error") or s == "error":
        return "not_run: error"
    if s == "malformed_tool_call":
        return "malformed_tool_call"
    if s == "length":
        return "output-length cap"
    if s in FORCED:
        return FORCED[s]
    if s in ANSWERED:
        return "answered"
    return f"other: {s}"


def finished(r: dict) -> bool:
    return taxonomy(r) == "answered"


# --------------------------------------------------------------------------- pairs


def make_pairs(a_rows: list[dict], b_rows: list[dict], size: str) -> list[dict]:
    """Pairs on (task, seed) at one size; A is the harness arm, B the plain arm."""
    ka = {(r["task"], seed_of(r)): r for r in a_rows if r["size"] == size}
    kb = {(r["task"], seed_of(r)): r for r in b_rows if r["size"] == size}
    return [
        {"task": t, "seed": s, "a": ka[(t, s)], "b": kb[(t, s)]}
        for (t, s) in sorted(set(ka) & set(kb))
    ]


def exclusion_sets(pairs: list[dict]) -> OrderedDict[str, tuple[str, list[dict]]]:
    """Decision 9 (TEST-PLAN 1d): primary, one secondary, three sensitivity-only sets."""
    out: OrderedDict[str, tuple[str, list[dict]]] = OrderedDict()
    out["primary: every pair counts"] = ("primary", list(pairs))
    out["secondary: plain does_not_fit pairs dropped"] = (
        "secondary",
        [p for p in pairs if taxonomy(p["b"]) != "not_run: does_not_fit"],
    )
    out["sensitivity: plain length rows dropped"] = (
        "sensitivity",
        [p for p in pairs if taxonomy(p["b"]) != "output-length cap"],
    )
    out["sensitivity: harness turn-cap/timeout rows dropped"] = (
        "sensitivity",
        [p for p in pairs if p["a"].get("stop_reason") not in ("max_iterations", "timeout")],
    )
    out["sensitivity: both arms finished"] = (
        "sensitivity",
        [p for p in pairs if finished(p["a"]) and finished(p["b"])],
    )
    return out


# --------------------------------------------------------------------------- tests


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def mcnemar(pairs: list[dict]) -> dict:
    b = sum(exact(p["a"]) and not exact(p["b"]) for p in pairs)
    c = sum(exact(p["b"]) and not exact(p["a"]) for p in pairs)
    n = len(pairs)
    z = (b - c) / math.sqrt(b + c) if b + c else 0.0
    return {
        "n": n,
        "a_exact": sum(exact(p["a"]) for p in pairs),
        "b_exact": sum(exact(p["b"]) for p in pairs),
        "b": b,
        "c": c,
        "z": z,
        "p": mcnemar_exact(b, c),
        "diff": ((b - c) / n) if n else float("nan"),
        "discordance": ((b + c) / n) if n else float("nan"),
    }


def _diffs(pairs: list[dict]) -> tuple[float, float]:
    n = len(pairs)
    de = sum(int(exact(p["a"])) - int(exact(p["b"])) for p in pairs) / n
    ds = sum(score(p["a"]) - score(p["b"]) for p in pairs) / n
    return de, ds


def cluster_bootstrap(pairs: list[dict], rng: random.Random, reps: int = BOOT) -> dict:
    """Resample tasks with replacement, then pairs within each drawn task."""
    by_task: dict[str, list[dict]] = {}
    for p in pairs:
        by_task.setdefault(p["task"], []).append(p)
    tasks = sorted(by_task)
    if not tasks:
        return {"n_tasks": 0}
    de_s, ds_s = [], []
    for _ in range(reps):
        sample: list[dict] = []
        for _ in tasks:
            t = tasks[rng.randrange(len(tasks))]
            rows = by_task[t]
            sample.extend(rows[rng.randrange(len(rows))] for _ in rows)
        de, ds = _diffs(sample)
        de_s.append(de)
        ds_s.append(ds)
    de_s.sort()
    ds_s.sort()
    lo, hi = int(0.025 * reps), int(0.975 * reps) - 1
    de0, ds0 = _diffs(pairs)
    return {
        "n_tasks": len(tasks),
        "exact_diff": de0,
        "exact_diff_ci": (de_s[lo], de_s[hi]),
        "score_diff": ds0,
        "score_diff_ci": (ds_s[lo], ds_s[hi]),
        "reps": reps,
    }


# ----------------------------------------------------------------- GLMM (pure Python)


def hermite_gauss(n: int) -> list[tuple[float, float]]:
    """Nodes and weights for int f(x) exp(-x^2) dx (physicists' Hermite), Newton on the
    three-term recurrence (Numerical Recipes gauher)."""
    nodes: list[tuple[float, float]] = []
    pim4 = math.pi**-0.25
    z = 0.0
    for i in range((n + 1) // 2):
        if i == 0:
            z = math.sqrt(2 * n + 1) - 1.85575 * (2 * n + 1) ** (-1 / 6)
        elif i == 1:
            z -= 1.14 * n**0.426 / z
        elif i == 2:
            z = 1.86 * z - 0.86 * nodes[0][0]
        elif i == 3:
            z = 1.91 * z - 0.91 * nodes[1][0]
        else:
            z = 2.0 * z - nodes[i - 2][0]
        for _ in range(100):
            p1, p2 = pim4, 0.0
            for j in range(1, n + 1):
                p3 = p2
                p2 = p1
                p1 = z * math.sqrt(2.0 / j) * p2 - math.sqrt((j - 1) / j) * p3
            pp = math.sqrt(2 * n) * p2
            z1 = z
            z = z1 - p1 / pp
            if abs(z - z1) < 1e-14:
                break
        w = 2.0 / (pp * pp)
        nodes.append((z, w))
    full = [(x, w) for x, w in nodes] + [(-x, w) for x, w in nodes if x != 0.0]
    return sorted(full)


def _sigmoid(x: float) -> float:
    if x >= 0:
        e = math.exp(-x)
        return 1 / (1 + e)
    e = math.exp(x)
    return e / (1 + e)


def _loglik(theta: tuple[float, float, float], clusters: list[list[tuple[int, int]]], gh) -> float:
    """Marginal log-likelihood of a random-intercept logit: y ~ b0 + b1*arm + u_task,
    u ~ N(0, sigma^2), integrated by Gauss-Hermite."""
    b0, b1, ls = theta
    sigma = math.exp(ls)
    total = 0.0
    for obs in clusters:
        acc = 0.0
        for x, w in gh:
            u = math.sqrt(2) * sigma * x
            ll = 0.0
            for arm, y in obs:
                eta = b0 + b1 * arm + u
                p = _sigmoid(eta)
                p = min(max(p, 1e-12), 1 - 1e-12)
                ll += math.log(p) if y else math.log(1 - p)
            acc += w * math.exp(ll)
        total += math.log(max(acc / math.sqrt(math.pi), 1e-300))
    return total


def nelder_mead(
    f: Callable[[list[float]], float],
    x0: list[float],
    step: float = 0.5,
    iters: int = 2000,
    tol: float = 1e-9,
) -> list[float]:
    n = len(x0)
    pts = [list(x0)]
    for i in range(n):
        x = list(x0)
        x[i] += step
        pts.append(x)
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if (
            abs(vals[-1] - vals[0]) < tol
            and max(abs(pts[-1][k] - pts[0][k]) for k in range(n)) < tol
        ):
            break
        cen = [sum(p[k] for p in pts[:-1]) / n for k in range(n)]
        xr = [cen[k] + (cen[k] - pts[-1][k]) for k in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [cen[k] + 2 * (cen[k] - pts[-1][k]) for k in range(n)]
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = [cen[k] + 0.5 * (pts[-1][k] - cen[k]) for k in range(n)]
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][k] + 0.5 * (pts[i][k] - pts[0][k]) for k in range(n)]
                    vals[i] = f(pts[i])
    return pts[0]


def _invert3(m: list[list[float]]) -> list[list[float]] | None:
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(3)] for i, row in enumerate(m)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return None
        a[col], a[piv] = a[piv], a[col]
        f = a[col][col]
        a[col] = [v / f for v in a[col]]
        for r in range(3):
            if r != col:
                g = a[r][col]
                a[r] = [v - g * w for v, w in zip(a[r], a[col], strict=True)]
    return [row[3:] for row in a]


def glmm_logit(pairs: list[dict], nodes: int = 20) -> dict:
    """Random-intercept logit on exactness: arm fixed effect (harness=1, plain=0), task
    random intercept. Returns the arm coefficient, its Wald SE/z/p, the odds ratio and
    the task SD. Falls back to a flagged result when the Hessian is singular."""
    by_task: dict[str, list[tuple[int, int]]] = {}
    for p in pairs:
        by_task.setdefault(p["task"], []).append((1, int(exact(p["a"]))))
        by_task[p["task"]].append((0, int(exact(p["b"]))))
    clusters = list(by_task.values())
    if not clusters:
        return {"ok": False, "reason": "no pairs"}
    gh = hermite_gauss(nodes)
    ys = [y for obs in clusters for _, y in obs]
    pbar = min(max(sum(ys) / len(ys), 0.02), 0.98)

    def neg(th: list[float]) -> float:
        # Box constraints keep a separated sample from running to infinity: |beta| <= 10,
        # task SD <= 10 (odds ratio 2e4 and SD 10 are already "not identifiable").
        pen = sum(max(0.0, abs(v) - 10.0) ** 2 for v in th) * 1e3
        return -_loglik((th[0], th[1], th[2]), clusters, gh) + pen

    th = nelder_mead(neg, [math.log(pbar / (1 - pbar)), 0.0, math.log(0.5)])
    th = nelder_mead(neg, th, step=0.1)
    separated = abs(th[1]) > 8.0 or th[2] > math.log(8.0)
    h = 1e-4
    hess = [[0.0] * 3 for _ in range(3)]
    f0 = neg(th)
    for i in range(3):
        for j in range(3):
            tpp = list(th)
            tpp[i] += h
            tpp[j] += h
            tpm = list(th)
            tpm[i] += h
            tpm[j] -= h
            tmp = list(th)
            tmp[i] -= h
            tmp[j] += h
            tmm = list(th)
            tmm[i] -= h
            tmm[j] -= h
            hess[i][j] = (neg(tpp) - neg(tpm) - neg(tmp) + neg(tmm)) / (4 * h * h)
    cov = _invert3(hess)
    b1 = th[1]
    se = math.sqrt(cov[1][1]) if cov and cov[1][1] > 0 else float("nan")
    z = b1 / se if se == se and se > 0 else float("nan")
    p = math.erfc(abs(z) / math.sqrt(2)) if z == z else float("nan")
    ok = cov is not None and se == se and not separated
    return {
        "ok": ok,
        "reason": None
        if ok
        else (
            "separation: a task has all-right or all-wrong answers in one arm, "
            "so the arm effect or the task SD is not identifiable at this n"
            if separated
            else "singular Hessian"
        ),
        "beta_arm": b1,
        "se": se,
        "z": z,
        "p": p,
        "odds_ratio": math.exp(b1),
        "intercept": th[0],
        "sigma_task": math.exp(th[2]),
        "loglik": -f0,
        "n_obs": len(ys),
        "n_tasks": len(clusters),
    }


# ------------------------------------------------------------------- LOTO and MDE


def leave_one_task_out(pairs: list[dict]) -> list[dict]:
    tasks = sorted({p["task"] for p in pairs})
    out = []
    for t in tasks:
        sub = [p for p in pairs if p["task"] != t]
        m = mcnemar(sub)
        out.append({"dropped": t, **m})
    return out


def mde(n_pairs: int, discordance: float, z_alpha: float, z_beta: float = Z_BETA_80) -> float:
    """Minimum detectable difference in exact-match rate (A minus B) at a boundary
    z_alpha with 80% power, for n pairs and discordance rate pd: the paired-difference
    SE is about sqrt(pd / n) when the effect is small, so MDE = (z_a + z_b) * sqrt(pd / n)."""
    if n_pairs <= 0 or discordance != discordance or discordance <= 0:
        return float("nan")
    return (z_alpha + z_beta) * math.sqrt(discordance / n_pairs)


# ------------------------------------------------------------- breakdowns and cost


def breakdown(pairs: list[dict], key: Callable[[dict], str]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for p in pairs:
        groups.setdefault(key(p), []).append(p)
    return [{"group": g, **mcnemar(ps)} for g, ps in sorted(groups.items())]


def author_of(p: dict) -> str:
    r = p["a"]
    return f"{r.get('author_vendor') or '?'} / {r.get('author_model') or '?'}"


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = min(len(xs) - 1, max(0, math.ceil(q * len(xs)) - 1))
    return xs[i]


def cost(rows: list[dict]) -> dict:
    att = [r for r in rows if taxonomy(r) != "not_run: does_not_fit"]

    def col(k: str) -> list[float]:
        return [float(r[k]) for r in att if r.get(k) is not None]

    secs = col("seconds")
    return {
        "n": len(rows),
        "attempted": len(att),
        "finished": sum(finished(r) for r in rows),
        "completion_rate": (sum(finished(r) for r in rows) / len(rows)) if rows else float("nan"),
        "sec_p50": statistics.median(secs) if secs else float("nan"),
        "sec_p95": _pct(secs, 0.95),
        "prompt_tokens_mean": statistics.fmean(col("prompt_tokens"))
        if col("prompt_tokens")
        else float("nan"),
        "completion_tokens_mean": statistics.fmean(col("completion_tokens"))
        if col("completion_tokens")
        else float("nan"),
        "subcalls_mean": statistics.fmean(col("subcalls")) if col("subcalls") else float("nan"),
        "turns_mean": statistics.fmean(col("turns")) if col("turns") else float("nan"),
        "taxonomy": dict(Counter(taxonomy(r) for r in rows)),
    }


# ------------------------------------------------------------ evidence position


def _load_generator(lane: str, manifest: dict):
    entry = manifest["generators"][lane]["active"]
    path = INDEP / entry["file"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise RuntimeError(f"{entry['file']} does not match its pinned sha256")
    spec = importlib.util.spec_from_file_location(f"h1_gen_{lane}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _answer_strings(answer) -> list[str]:
    """Literal strings whose last mention locates the deciding fact; derived values
    (sums, dicts of totals) yield none."""
    if isinstance(answer, str):
        return [answer] if answer and not answer.startswith("$") else []
    if isinstance(answer, (list, tuple)):
        return [s for a in answer for s in _answer_strings(a) if isinstance(a, str)]
    if isinstance(answer, dict):
        out = []
        for v in answer.values():
            if isinstance(v, str) and len(v) > 2 and not v.replace(".", "").isdigit():
                out.append(v)
        return out
    return []


def evidence_position(context: str, answer) -> str:
    strings = _answer_strings(answer)
    hits = [context.rfind(s) for s in strings if s in context]
    if not hits:
        return "computed"
    frac = max(hits) / max(1, len(context))
    return "first third" if frac < 1 / 3 else "middle third" if frac < 2 / 3 else "last third"


def evidence_positions(
    cells: set[tuple[str, str, int]], manifest: dict, cache: Path | None
) -> dict[str, str]:
    """{"task|size|seed": bucket}; cached because generate() at medium is slow."""
    known: dict[str, str] = {}
    if cache and cache.exists():
        known = json.loads(cache.read_text(encoding="utf-8"))
    mods: dict[str, object] = {}
    changed = False
    for task, size, seed in sorted(cells):
        key = f"{task}|{size}|{seed}"
        if key in known:
            continue
        if task not in mods:
            mods[task] = _load_generator(task, manifest)
        d = mods[task].generate(seed, size)  # type: ignore[attr-defined]
        known[key] = evidence_position(d["context"], d["answer"])
        changed = True
    if cache and changed:
        cache.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return known


# ------------------------------------------------------------------ A/A floor


def aa_floor(plain_small: list[dict], plain_big: list[dict]) -> dict:
    pairs = make_pairs(plain_small, plain_big, "small")
    both_fit = [
        p
        for p in pairs
        if taxonomy(p["a"]) != "not_run: does_not_fit"
        and taxonomy(p["b"]) != "not_run: does_not_fit"
    ]
    disc = sum(exact(p["a"]) != exact(p["b"]) for p in both_fit)
    return {
        "pairs": len(pairs),
        "both_fit": len(both_fit),
        "discordant": disc,
        "rate": (disc / len(both_fit)) if both_fit else float("nan"),
    }


# ------------------------------------------------------------------ orchestration


def analyse(
    harness: list[dict],
    plain: list[dict],
    look: int,
    rng: random.Random,
    positions: dict[str, str] | None = None,
    reps: int = BOOT,
    glmm: bool = True,
) -> dict:
    z_alpha = BOUNDARIES[look]
    out: dict = {"look": look, "boundary": z_alpha, "sizes": {}}
    for size in SIZES:
        pairs = make_pairs(harness, plain, size)
        if not pairs:
            continue
        sets = exclusion_sets(pairs)
        res: dict = {"sets": OrderedDict()}
        for name, (kind, ps) in sets.items():
            m = mcnemar(ps)
            m["kind"] = kind
            m["crossed"] = abs(m["z"]) > z_alpha
            res["sets"][name] = m
        prim = res["sets"]["primary: every pair counts"]
        res["bootstrap"] = cluster_bootstrap(pairs, rng, reps)
        res["glmm"] = glmm_logit(pairs) if glmm else {"ok": False, "reason": "skipped"}
        res["loto"] = leave_one_task_out(pairs)
        res["mde"] = {
            f"look {k} ({n} pairs)": mde(n, prim["discordance"], BOUNDARIES[k])
            for k, n in LOOK_PAIRS.items()
        }
        res["mde_observed_n"] = mde(prim["n"], prim["discordance"], z_alpha)
        res["by_task"] = breakdown(pairs, lambda p: p["task"])
        res["by_author"] = breakdown(pairs, author_of)
        if positions:

            def pos_of(p: dict, _size: str = size) -> str:
                return positions.get(f"{p['task']}|{_size}|{p['seed']}", "unknown")

            res["by_position"] = breakdown(pairs, pos_of)
        res["cost"] = {
            "harness": cost([p["a"] for p in pairs]),
            "plain": cost([p["b"] for p in pairs]),
        }
        out["sizes"][size] = res
    return out


# ------------------------------------------------------------------ rendering


def _f(x: float, d: int = 3) -> str:
    return "--" if x != x else f"{x:.{d}f}"


def _ci(t: tuple[float, float]) -> str:
    return f"[{_f(t[0])}, {_f(t[1])}]"


def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
        *("| " + " | ".join(r) + " |" for r in rows),
    ]


def _mc_cells(m: dict) -> list[str]:
    return [str(m["n"]), str(m["a_exact"]), str(m["b_exact"]), str(m["b"]), str(m["c"])]


def _glmm_line(g: dict) -> str:
    if not g.get("ok"):
        return f"- not available: {g.get('reason', 'singular Hessian')}"
    return (
        f"- arm (harness vs plain): beta {g['beta_arm']:+.3f}, SE {_f(g['se'])}, "
        f"Wald z {g['z']:+.2f}, p {_f(g['p'], 4)}, odds ratio {g['odds_ratio']:.2f}; "
        f"task SD {g['sigma_task']:.2f}; {g['n_obs']} answers in {g['n_tasks']} tasks"
    )


def render_markdown(res: dict, aa: dict | None, label: str) -> str:
    L = [f"# H1 analysis: harness v0.1 32K vs plain-128K ({label})", ""]
    L.append(
        f"Look {res['look']}, boundary |z| > {res['boundary']}. Pairs on (task, seed); "
        "A = harness, B = plain; b = A right / B wrong, c = A wrong / B right."
    )
    mc_head = ["n", "A exact", "B exact", "b", "c", "z", "exact p"]
    for size, r in res["sizes"].items():
        L += ["", f"## {size}", "", "### Exclusion sets (decision 9)", ""]
        L += _md_table(
            ["set", "kind", *mc_head, "crossed"],
            [
                [
                    name,
                    m["kind"],
                    *_mc_cells(m),
                    f"{m['z']:+.3f}",
                    _f(m["p"], 4),
                    "yes" if m["crossed"] else "no",
                ]
                for name, m in r["sets"].items()
            ],
        )
        bs = r["bootstrap"]
        L += ["", "### Task-clustered paired bootstrap (primary set)", ""]
        L.append(
            f"- exact-rate difference A-B: {bs['exact_diff']:+.3f}, "
            f"95% CI {_ci(bs['exact_diff_ci'])} "
            f"({bs['n_tasks']} task clusters, {bs['reps']} resamples)"
        )
        L.append(
            f"- mean-score difference A-B: {bs['score_diff']:+.3f}, "
            f"95% CI {_ci(bs['score_diff_ci'])}"
        )
        L += ["", "### GLMM: logit(exact) ~ arm + (1 | task)", "", _glmm_line(r["glmm"])]
        L += ["", "### Leave-one-task-out (primary)", ""]
        L += _md_table(
            ["dropped", *mc_head, "diff"],
            [
                [m["dropped"], *_mc_cells(m), f"{m['z']:+.3f}", _f(m["p"], 4), f"{m['diff']:+.3f}"]
                for m in r["loto"]
            ],
        )
        pd = r["sets"]["primary: every pair counts"]["discordance"]
        L += ["", f"### Minimum detectable effect (80% power, observed discordance {_f(pd)})", ""]
        for k, v in r["mde"].items():
            L.append(f"- {k}: {_f(v)} in exact-rate difference")
        L.append(f"- at the observed n with this look's boundary: {_f(r['mde_observed_n'])}")
        for title, key in (
            ("Per task", "by_task"),
            ("Per generator author", "by_author"),
            ("Per evidence position", "by_position"),
        ):
            if key not in r:
                continue
            L += ["", f"### {title}", ""]
            if key == "by_position":
                L += [
                    "Position = the third of the context holding the answer's last literal "
                    "mention; 'computed' = the answer never appears verbatim (sums, tallies). "
                    "Where a task's position never varies across seeds this regroups tasks, "
                    "so read it beside the per-task table.",
                    "",
                ]
            L += _md_table(
                ["group", *mc_head],
                [[m["group"], *_mc_cells(m), f"{m['z']:+.3f}", _f(m["p"], 4)] for m in r[key]],
            )
        L += ["", "### Completion, cost and latency", ""]
        cost_head = ["arm", "n", "finished", "completion", "s p50", "s p95"]
        cost_head += ["prompt tok", "completion tok", "sub-calls", "turns"]
        L += _md_table(
            cost_head,
            [
                [
                    arm,
                    str(c["n"]),
                    str(c["finished"]),
                    _f(c["completion_rate"], 2),
                    _f(c["sec_p50"], 0),
                    _f(c["sec_p95"], 0),
                    _f(c["prompt_tokens_mean"], 0),
                    _f(c["completion_tokens_mean"], 0),
                    _f(c["subcalls_mean"], 2),
                    _f(c["turns_mean"], 2),
                ]
                for arm, c in r["cost"].items()
            ],
        )
        tax_h, tax_p = r["cost"]["harness"]["taxonomy"], r["cost"]["plain"]["taxonomy"]
        L += ["", "### Failure taxonomy", ""]
        L += _md_table(
            ["category", "harness", "plain"],
            [
                [cat, str(tax_h.get(cat, 0)), str(tax_p.get(cat, 0))]
                for cat in sorted(set(tax_h) | set(tax_p))
            ],
        )
    if aa:
        L += ["", "## A/A noise floor: plain-32K vs plain-128K at small", ""]
        L.append(
            f"- {aa['pairs']} cells, {aa['both_fit']} where both fit; exactness differs on "
            f"{aa['discordant']} ({_f(aa['rate'])}). Identical input, identical model: this is "
            "the per-row noise any paired delta must clear."
        )
    L += ["", "*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*", ""]
    return "\n".join(L)


def render_latex(res: dict, label: str) -> str:
    L = [
        f"% Generated by paper/analysis/h1_analysis.py ({label}). Do not edit.",
        "\\begin{table}[t]",
        "\\centering\\small",
        "\\setlength{\\tabcolsep}{4pt}",
        f"\\caption{{H1, harness v0.1 32K vs plain-128K, look {res['look']} "
        f"(boundary $|z| > {res['boundary']}$). Primary: every pair counts. Secondary and "
        "sensitivity sets per TEST-PLAN 1d. Bootstrap: task-clustered paired, 95\\%. "
        "GLMM: logit, arm fixed effect, task random intercept.}",
        "\\label{tab:h1-analysis}",
        "\\begin{tabular}{llrrrrrl}",
        "\\toprule",
        "Size & Set & $n$ & A ex. & B ex. & $b$/$c$ & $z$ & $p$ \\\\",
        "\\midrule",
    ]
    for size, r in res["sizes"].items():
        first = True
        for raw_name, m in r["sets"].items():
            name = raw_name.replace("_", "\\_")
            L.append(
                f"{size if first else ''} & {name} & {m['n']} & {m['a_exact']} & {m['b_exact']} "
                f"& {m['b']}/{m['c']} & ${m['z']:+.2f}$ & {_f(m['p'], 3)} \\\\"
            )
            first = False
        bs, g = r["bootstrap"], r["glmm"]
        glmm = (
            f"GLMM arm OR {g['odds_ratio']:.2f}, $z={g['z']:+.2f}$, $p={_f(g['p'], 3)}$, "
            f"task SD {g['sigma_task']:.2f}"
            if g.get("ok")
            else "GLMM n/a"
        )
        L.append(
            f" & \\multicolumn{{7}}{{l}}{{bootstrap $\\Delta$exact {bs['exact_diff']:+.3f} "
            f"{_ci(bs['exact_diff_ci'])}; {glmm}}} \\\\"
        )
        L.append("\\midrule")
    L[-1] = "\\bottomrule"
    L += ["\\end{tabular}", "\\end{table}", ""]
    return "\n".join(L)


def parse_seeds(text: str | None) -> set[int] | None:
    if not text:
        return None
    out: set[int] = set()
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--runs",
        type=Path,
        default=REPO / "runs/exp-v02/rescored-round4",
        help="dir with h-v01-32k.json and plain-131k.json",
    )
    ap.add_argument(
        "--aa-runs",
        type=Path,
        default=None,
        help="dir with plain-32k.json and plain-131k.json for the A/A floor",
    )
    ap.add_argument(
        "--seeds", default=None, help=f"e.g. 4-43 (default: {CONFIRMATORY_FROM} onward)"
    )
    ap.add_argument("--look", type=int, choices=(1, 2, 3), default=3)
    ap.add_argument("--reps", type=int, default=BOOT)
    ap.add_argument("--no-glmm", action="store_true")
    ap.add_argument("--no-positions", action="store_true")
    ap.add_argument("--positions-cache", type=Path, default=HERE / "evidence_positions.json")
    ap.add_argument("--out", type=Path, default=None, help="write main_h1_analysis.tex here")
    ap.add_argument("--report", type=Path, default=None, help="write the markdown report here")
    ap.add_argument("--json", type=Path, default=None, help="write the raw results here")
    args = ap.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    harness = load_rows(args.runs / f"{HARNESS}.json", seeds)
    plain = load_rows(args.runs / f"{PLAIN}.json", seeds)
    if seeds is None:
        harness = [r for r in harness if seed_of(r) >= CONFIRMATORY_FROM]
        plain = [r for r in plain if seed_of(r) >= CONFIRMATORY_FROM]
    positions = None
    if not args.no_positions:
        manifest = json.loads((INDEP / "manifest.json").read_text(encoding="utf-8"))
        cells = {(r["task"], r["size"], seed_of(r)) for r in harness if r["size"] in SIZES}
        positions = evidence_positions(cells, manifest, args.positions_cache)
    rng = random.Random(RNG_SEED)
    res = analyse(harness, plain, args.look, rng, positions, args.reps, not args.no_glmm)
    aa = None
    if args.aa_runs:
        ps = load_rows(args.aa_runs / f"{PLAIN_SMALL}.json", seeds)
        pb = load_rows(args.aa_runs / f"{PLAIN}.json", seeds)
        aa = aa_floor(ps, pb)
    label = f"seeds {args.seeds or f'{CONFIRMATORY_FROM}+'}; {args.runs}"
    md = render_markdown(res, aa, label)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(md, encoding="utf-8")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "main_h1_analysis.tex").write_text(render_latex(res, label), encoding="utf-8")
    if args.json:
        args.json.write_text(
            json.dumps({"results": res, "aa": aa}, indent=1, default=str), encoding="utf-8"
        )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
