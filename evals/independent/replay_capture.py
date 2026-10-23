"""Temperature-0 replay set on the current serving stack (issue #97, epic #80).

    uv run python evals/independent/replay_capture.py --dry-run
    uv run python evals/independent/replay_capture.py --pass 1
    uv run python evals/independent/replay_capture.py --pass 2
    uv run python evals/independent/replay_capture.py --compare \\
        runs/replay/stackA-pass1.jsonl runs/replay/stackA-pass2.jsonl

An engine-equivalence instrument, not a result. It sends a fixed set of requests, built
deterministically from the frozen generators, with every role's sampling as the arm ran it
except ``temperature`` forced to 0, and records the raw completion. Two passes on the same
stack give the engine's own run-to-run noise floor; a later stack is judged against that.

Per instance (task x size x seed) three request shapes:

- ``plain``: the plain-128K request exactly as ``bench.run_plain`` builds it (profile
  ``pluto-long``, root role, thinking as the profile sets it, the arm's output budget).
  Medium prompts above the arm's usable window are included: the arm never sent them, but
  the stack serves 262K and the panel asked for real 65-148K prompts.
- ``root``: the harness v0.1 root's first turn (system prompt + query + turn 1 prompt,
  profile ``pluto``, root role).
- ``sub``: one ``llm_query``-shaped call (question + the first 12,000 characters, sub role,
  thinking off). The harness's real sub-call prompts are model-written and were not logged,
  so this is a representative shape, not a replay of a recorded prompt.

Every record carries the request's sha256, so a later pass is comparable only if the
request bytes match. Resumable: a (pass, kind, task, size, seed) already in the output
file with no error is skipped. Nothing here scores a paper result.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "examples"))
sys.path.insert(0, str(HERE))

import bench  # noqa: E402
import run_eval  # noqa: E402

from reclamo.config import load_config, resolve_api_key  # noqa: E402
from reclamo.prompts import build_system_prompt, turn_prompt  # noqa: E402
from reclamo.rlm import describe_context  # noqa: E402

KINDS = ("plain", "root", "sub")
DEFAULT_SEEDS = (4, 5, 6)
DEFAULT_SIZES = ("small", "medium")
SUB_CHARS = 12_000
OUT_DIR = REPO / "runs" / "replay"


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _temp0(cfg: Any) -> Any:
    """The profile's config with every role's temperature forced to 0."""
    root = dataclasses.replace(cfg.root, sampling={**cfg.root.sampling, "temperature": 0.0})
    sub = dataclasses.replace(cfg.sub, sampling={**cfg.sub.sampling, "temperature": 0.0})
    return dataclasses.replace(cfg, root=root, sub=sub)


@dataclasses.dataclass
class Job:
    kind: str
    task: str
    size: str
    seed: int
    role: str
    messages: list[dict[str, str]]
    enable_thinking: bool
    max_tokens: int | None
    est_prompt_tokens: int
    fits_arm: bool | None

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.kind, self.task, self.size, self.seed)

    @property
    def request_sha256(self) -> str:
        return _sha(
            {
                "messages": self.messages,
                "role": self.role,
                "enable_thinking": self.enable_thinking,
                "max_tokens": self.max_tokens,
            }
        )


def build_jobs(
    gens: run_eval.Generators,
    cfg_plain: Any,
    cfg_rlm: Any,
    kinds: list[str],
    sizes: list[str],
    seeds: list[int],
    lanes: list[str],
) -> list[Job]:
    jobs: list[Job] = []
    for size in sizes:
        for seed in seeds:
            for lane in lanes:
                inst = run_eval.build_instance(gens, lane, size, seed)
                if "plain" in kinds:
                    fits, est, _usable = bench.fit_decision(cfg_plain, inst.context, inst.query)
                    jobs.append(
                        Job(
                            "plain", lane, size, seed, "root",
                            bench.plain_messages(inst.context, inst.query),
                            cfg_plain.root.enable_thinking,
                            bench.plain_output_tokens(cfg_plain, est, bench.PLAIN_MAX_TOKENS),
                            est, fits,
                        )
                    )  # fmt: skip
                if "root" in kinds:
                    _kind, meta = describe_context(inst.context)
                    msgs = [
                        {"role": "system", "content": build_system_prompt(cfg_rlm, meta)},
                        {
                            "role": "user",
                            "content": f"{inst.query}\n\n"
                            f"{turn_prompt(1, cfg_rlm.max_iterations, first=True)}",
                        },
                    ]
                    est = bench.estimate_tokens("".join(m["content"] for m in msgs))
                    jobs.append(
                        Job("root", lane, size, seed, "root", msgs,
                            cfg_rlm.root.enable_thinking, None, est, None)
                    )  # fmt: skip
                if "sub" in kinds:
                    prompt = (
                        "Answer the question using only this excerpt. If the excerpt does not "
                        f"contain the answer, say so.\n\nQuestion: {inst.query}\n\n"
                        f"Excerpt:\n{inst.context[:SUB_CHARS]}"
                    )
                    msgs = [{"role": "user", "content": prompt}]
                    jobs.append(
                        Job("sub", lane, size, seed, "sub", msgs,
                            cfg_rlm.sub.enable_thinking, None,
                            bench.estimate_tokens(prompt), None)
                    )  # fmt: skip
    return jobs


def load_done(path: Path) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    done: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("type") != "request" or rec.get("error"):
            continue
        done[(rec["kind"], rec["task"], rec["size"], int(rec["seed"]))] = rec
    return done


def run_pass(
    args: argparse.Namespace, jobs: list[Job], out: Path, provenance: dict[str, Any]
) -> int:
    cfg_plain = _temp0(load_config("pluto-long", args.profiles))
    cfg_rlm = _temp0(
        dataclasses.replace(load_config("pluto", args.profiles), prompt_version="v0.1")
    )
    from reclamo.client import LMClient

    client_plain = LMClient(cfg_plain, resolve_api_key(cfg_plain))
    client_rlm = LMClient(cfg_rlm, resolve_api_key(cfg_rlm))

    done = load_done(out)
    todo = [j for j in jobs if j.key not in done]
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if not out.exists():
        header = {
            "type": "meta",
            "pass": args.pass_n,
            "created": stamp,
            "seeds": sorted({j.seed for j in jobs}),
            "sizes": sorted({j.size for j in jobs}),
            "kinds": sorted({j.kind for j in jobs}),
            "temperature": 0.0,
            "profiles": {
                "plain": {
                    "name": cfg_plain.name,
                    "base_url": cfg_plain.base_url,
                    "model": cfg_plain.root.model,
                    "root_sampling": cfg_plain.root.sampling,
                    "context_tokens": cfg_plain.context_tokens,
                    "usable_tokens": bench.usable_tokens(cfg_plain),
                    "plain_max_tokens": bench.PLAIN_MAX_TOKENS,
                },
                "rlm": {
                    "name": cfg_rlm.name,
                    "base_url": cfg_rlm.base_url,
                    "model": cfg_rlm.root.model,
                    "prompt_version": cfg_rlm.prompt_version,
                    "root_sampling": cfg_rlm.root.sampling,
                    "sub_sampling": cfg_rlm.sub.sampling,
                    "max_iterations": cfg_rlm.max_iterations,
                },
            },  # fmt: skip
            "sub_chars": SUB_CHARS,
            "active_sha256": {lane: provenance_manifest(lane) for lane in run_eval.LANES},
            "provenance": provenance,
            **run_eval.provenance(),
        }
        out.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"pass {args.pass_n}: {len(todo)} requests to send, {len(done)} already in {out}",
        file=sys.stderr,
    )

    def one(job: Job) -> dict[str, Any]:
        client = client_plain if job.kind == "plain" else client_rlm
        rec: dict[str, Any] = {
            "type": "request",
            "pass": args.pass_n,
            "kind": job.kind,
            "task": job.task,
            "size": job.size,
            "seed": job.seed,
            "role": job.role,
            "request_sha256": job.request_sha256,
            "prompt_chars": sum(len(m["content"]) for m in job.messages),
            "est_prompt_tokens": job.est_prompt_tokens,
            "fits_arm": job.fits_arm,
            "enable_thinking": job.enable_thinking,
            "max_tokens": job.max_tokens,
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        t0 = time.monotonic()
        try:
            c = client.complete(
                job.messages,
                job.role,
                enable_thinking=job.enable_thinking,
                max_tokens=job.max_tokens,
            )
        except Exception as exc:  # recorded, never hidden; --resume retries it
            first = str(exc).splitlines()[0] if str(exc) else ""
            rec.update(
                error=f"{type(exc).__name__}: {first}",
                latency=round(time.monotonic() - t0, 2),
            )
            return rec
        usage = c.usage
        rec.update(
            content=c.content,
            reasoning=c.reasoning,
            content_from_reasoning=c.content_from_reasoning,
            finish_reason=c.finish_reason,
            usage=None if usage is None else dataclasses.asdict(usage),
            latency=round(c.latency, 2),
            attempts=c.attempts,
            model=c.model,
            endpoint=c.endpoint,
            error=None,
        )
        return rec

    def log(msg: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)

    errors = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for n, rec in enumerate(pool.map(one, todo), 1):
            with lock:
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tag = f"[{n}/{len(todo)}] {rec['kind']} {rec['task']} {rec['size']} s{rec['seed']}"
            if rec.get("error"):
                errors += 1
                log(f"{tag}: ERROR {rec['error']}")
            else:
                u = rec.get("usage") or {}
                log(
                    f"{tag}: {rec['finish_reason']}, {u.get('prompt_tokens')}+"
                    f"{u.get('completion_tokens')} tok, {rec['latency']}s"
                )
    log(f"pass {args.pass_n} done: {len(todo) - errors} ok, {errors} errors -> {out}")
    return 1 if errors else 0


def provenance_manifest(lane: str) -> str:
    return run_eval.load_manifest()["generators"][lane]["active"]["sha256"]


def _first_divergence(a: str, b: str) -> int | None:
    if a == b:
        return None
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def compare(path_a: Path, path_b: Path, score_plain: bool = True) -> str:
    a, b = load_done(path_a), load_done(path_b)
    keys = sorted(set(a) & set(b))
    missing = sorted(set(a) ^ set(b))
    lines = [
        f"A = {path_a}  ({len(a)} ok)",
        f"B = {path_b}  ({len(b)} ok)",
        f"common {len(keys)}; only in one file {len(missing)}",
        "",
        "| kind | n | same request | same content | same reasoning | same finish | "
        "median first divergence (chars) |",
    ]
    lines.append("|---|---|---|---|---|---|---|")
    rows: dict[str, list[tuple[Any, ...]]] = {}
    for k in keys:
        ra, rb = a[k], b[k]
        same_req = ra["request_sha256"] == rb["request_sha256"]
        same_c = (ra.get("content") or "") == (rb.get("content") or "")
        same_r = (ra.get("reasoning") or "") == (rb.get("reasoning") or "")
        same_f = ra.get("finish_reason") == rb.get("finish_reason")
        div = _first_divergence(ra.get("content") or "", rb.get("content") or "")
        rows.setdefault(k[0], []).append((same_req, same_c, same_r, same_f, div))
        rows.setdefault("all", []).append((same_req, same_c, same_r, same_f, div))
    for kind in [*KINDS, "all"]:
        rs = rows.get(kind)
        if not rs:
            continue
        n = len(rs)
        divs = [d for *_x, d in rs if d is not None]
        med = f"{statistics.median(divs):.0f}" if divs else "–"
        lines.append(
            f"| {kind} | {n} | {sum(r[0] for r in rs)} | {sum(r[1] for r in rs)} | "
            f"{sum(r[2] for r in rs)} | {sum(r[3] for r in rs)} | {med} |"
        )
    if score_plain:
        gens = run_eval.Generators(run_eval.load_manifest())
        agree = total = 0
        both_exact = exact_a = exact_b = 0
        for k in keys:
            if k[0] != "plain":
                continue
            kind, lane, size, seed = k
            truth = gens.get(lane).generate(seed, size)["answer"]
            scorer = run_eval.generator_scorer(gens.get(lane))
            ea = scorer(a[k].get("content") or "", truth).correct
            eb = scorer(b[k].get("content") or "", truth).correct
            total += 1
            agree += ea == eb
            exact_a += ea
            exact_b += eb
            both_exact += ea and eb
        if total:
            lines += [
                "",
                f"plain exact under the ACTIVE scorers (diagnostic only): A {exact_a}/{total}, "
                f"B {exact_b}/{total}, agree on exactness {agree}/{total}",
            ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pass", dest="pass_n", type=int, default=None, help="pass number (1 or 2)")
    p.add_argument("--out", default=None, help="JSONL (default runs/replay/stackA-pass<N>.jsonl)")
    p.add_argument("--kinds", default=",".join(KINDS))
    p.add_argument("--sizes", default=",".join(DEFAULT_SIZES))
    p.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    p.add_argument("--tasks", default=",".join(run_eval.LANES))
    p.add_argument("--profiles", default=None, metavar="FILE")
    p.add_argument(
        "--concurrency", type=int, default=2, help="in-flight requests (Strata parallel=2)"
    )
    p.add_argument(
        "--provenance",
        default=str(OUT_DIR / "stackA-provenance.json"),
        help="JSON describing the serving stack, embedded in the pass header",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--compare", nargs=2, metavar=("A", "B"))
    p.add_argument("--no-score", action="store_true", help="--compare: skip the scorer agreement")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.compare:
        print(compare(Path(args.compare[0]), Path(args.compare[1]), not args.no_score))
        return 0
    kinds = [k for k in args.kinds.split(",") if k]
    sizes = [s for s in args.sizes.split(",") if s]
    seeds = [int(s) for s in args.seeds.split(",") if s]
    lanes = [t for t in args.tasks.split(",") if t]
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        print(f"replay_capture: unknown kind(s) {bad}", file=sys.stderr)
        return 2
    gens = run_eval.Generators(run_eval.load_manifest())
    cfg_plain = load_config("pluto-long", args.profiles)
    cfg_rlm = dataclasses.replace(load_config("pluto", args.profiles), prompt_version="v0.1")
    jobs = build_jobs(gens, cfg_plain, cfg_rlm, kinds, sizes, seeds, lanes)
    if args.dry_run:
        for j in jobs:
            fit = "" if j.fits_arm is None else ("fits arm" if j.fits_arm else "above arm window")
            print(
                f"{j.kind:5} {j.task:17} {j.size:7} seed={j.seed}  ~{j.est_prompt_tokens:>7,} tok  "
                f"max_tokens={j.max_tokens}  thinking={j.enable_thinking}  {fit}"
            )
        print(f"{len(jobs)} requests", file=sys.stderr)
        return 0
    if args.pass_n is None:
        print("replay_capture: --pass N is required (or --dry-run / --compare)", file=sys.stderr)
        return 2
    out = Path(args.out or OUT_DIR / f"stackA-pass{args.pass_n}.jsonl")
    prov_path = Path(args.provenance)
    provenance = (
        json.loads(prov_path.read_text()) if prov_path.exists() else {"note": "no provenance file"}
    )
    return run_pass(args, jobs, out, provenance)


if __name__ == "__main__":
    sys.exit(main())
