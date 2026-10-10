"""LongBench Pro loader (issue #75): practice, practice-dev and held-out items in the
harness's question format.

    uv run python evals/longbenchpro/longbenchpro.py download        # ~530 MB, sha256-checked
    uv run python evals/longbenchpro/longbenchpro.py stats           # counts and lengths
    uv run python evals/longbenchpro/longbenchpro.py stats --split held-out --max-bucket 32k
    uv run python evals/longbenchpro/longbenchpro.py exam-hashes     # rebuild exam_hashes.json

The source is ``caskcsg/LongBench-Pro`` on Hugging Face (Apache-2.0, arXiv 2601.02872):
one ``test`` split of 1,500 items in a single JSON file, 11 primary and 25 secondary
tasks, English and Chinese 750 each, six length buckets (8k-256k Qwen tokens). The file
is fetched at a pinned revision with the standard library and checked against its
sha256, so ``datasets`` is not needed.

- **Splits** come from a salted sha256 of an item id, never a random seed:
  ``practice`` (training data), ``practice-dev`` (recipe and checkpoint selection),
  ``held-out`` (evaluation only). The id hashed is the smallest in the item's
  *document group*: the 1,500 items have only 1,076 distinct contexts, and the same
  source text recurs across length buckets, so items whose contexts are equal or share a
  long line are grouped and always land in the same split. Hashing each id alone would
  put 135 shared contexts in more than one split.
- **MC vs open** is decided per item, not per task: an item is multiple choice when its
  answer is option letters that the question lists as options. ``mc`` is single-select;
  ``mc-multi`` allows several letters (any non-empty subset). The upstream scorer uses
  first-line exact match ("Accuracy") for T3 and T11, which are MC, but 83 of their 240
  items are multi-select, one is open, and T10 also has 62 MC items.
- **Exam exclusion:** an item whose normalised context or question hashes to one of the
  frozen ``evals/independent`` documents (``exam_hashes.json``) is refused, whatever
  its split.
- **Scoring** reimplements the upstream metrics per secondary task (Accuracy, SubEM,
  F1, pairwise accuracy, NDCG) from their definitions. T4 summaries need an embedding
  model and are left unscored (``scorable`` is False).

``instance(item)`` returns a ``bench.Instance`` whose task is registered in
``bench.TASKS``, so ``bench.run_rlm`` / ``bench.run_plain`` take it unchanged.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import statistics
import sys
import unicodedata
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "examples"))

import bench  # noqa: E402

DATASET = "caskcsg/LongBench-Pro"
REVISION = "4996884deae51f5e5d23c88da9d857fc54e5fa15"
FILENAME = "longbench_pro.json"
SHA256 = "92ff05f6088e212d06c5a731ab86000b69cee6a0900cbbd524a25851e3c30de0"
URL = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{FILENAME}"
DEFAULT_PATH = Path(
    os.environ.get("RECLAMO_LONGBENCHPRO", "~/.cache/reclamo/longbenchpro/" + FILENAME)
).expanduser()
EXAM_HASHES = HERE / "exam_hashes.json"
FIELDS = (
    "id",
    "context",
    "language",
    "token_length",
    "primary_task",
    "secondary_task",
    "contextual_requirement",
    "question_nonthinking",
    "question_thinking",
    "answer",
    "difficulty",
)

# --- splits ----------------------------------------------------------------------------

SPLITS = ("practice", "practice-dev", "held-out")
# Changing the salt or the bounds reshuffles every split; bump the version if you must.
SPLIT_SALT = "reclamo-longbenchpro-split-v1"
# Buckets of 100: [0, 70) practice, [70, 80) practice-dev, [80, 100) held-out.
SPLIT_BOUNDS = ((70, "practice"), (80, "practice-dev"), (100, "held-out"))


# A normalised line at least this long that two contexts share puts them in one group.
# 120 chars also catches the shorter paragraphs of Chinese statutes reused across items.
SHARED_LINE_CHARS = 120


def split_of(group_id: str) -> str:
    """The split for a document group, named by its smallest item id."""
    digest = hashlib.sha256(f"{SPLIT_SALT}:{group_id}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return next(name for bound, name in SPLIT_BOUNDS if bucket < bound)


def line_keys(context: str) -> set[bytes]:
    """The whole context plus every long line, normalised and hashed."""
    keys = {hashlib.blake2b(normalize(context).encode(), digest_size=16).digest()}
    for line in context.split("\n"):
        if len(line) >= SHARED_LINE_CHARS:
            text = normalize(line)
            if len(text) >= SHARED_LINE_CHARS:
                keys.add(hashlib.blake2b(text.encode(), digest_size=16).digest())
    return keys


def document_groups(items: list[Item]) -> dict[str, str]:
    """item id -> group id. Items are grouped when their contexts are equal or share a
    long line, transitively, so one document (or its 8k-256k cuts) never spans splits."""
    parent = {it.id: it.id for it in items}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[bytes, str] = {}
    for it in items:
        for key in line_keys(it.context):
            if key not in owner:
                owner[key] = it.id
                continue
            a, b = root(it.id), root(owner[key])
            if a != b:
                parent[max(a, b)] = min(a, b)  # the root is always the smallest id
    return {it.id: root(it.id) for it in items}


# --- multiple choice vs open -------------------------------------------------------------

KINDS = ("mc", "mc-multi", "open")
# An option line: "A.", "A、", "A:", "(A)", "A " or "A" directly before CJK text.
_OPTION = re.compile(r"(?m)^[ \t]*[(（]?([A-Z])(?:[)）.、．:：]|[ \t]|(?=[^\x00-\x7f]))")
# An output example that shows several letters at once: "A/AB/BCD/EFG", "AB/AC/ADE".
_MULTI_EXAMPLE = re.compile(r"\b[A-Z]{2,8}/[A-Z]{1,8}\b|\b[A-Z]/[A-Z]{2,8}\b")
_LETTERS = re.compile(r"[A-Z]+")


def options_of(question: str) -> list[str]:
    """Option letters the question lists, if they run A, B, C... with at least two."""
    seen = set(_OPTION.findall(question))
    letters = list(itertools.takewhile(seen.__contains__, "ABCDEFGHIJKLMNOP"))
    return letters if len(letters) >= 2 else []


def answer_kind(question: str, answer: list[str]) -> tuple[str, int]:
    """("mc" | "mc-multi" | "open", number of options; 0 for open)."""
    options = options_of(question)
    key = answer[0].strip() if len(answer) == 1 else ""
    if not options or not _LETTERS.fullmatch(key) or not set(key) <= set(options):
        return "open", 0
    multi = len(key) > 1 or bool(_MULTI_EXAMPLE.search(question))
    return ("mc-multi" if multi else "mc"), len(options)


def chance(kind: str, n_options: int) -> float | None:
    """Exact-match rate of a uniform random guess: 1/n single, 1/(2^n - 1) multi."""
    if kind == "mc":
        return 1 / n_options
    if kind == "mc-multi":
        return 1 / (2**n_options - 1)
    return None


# --- exam-hash exclusion -------------------------------------------------------------------


def normalize(text: str) -> str:
    """NFKC, casefold, every whitespace run collapsed to one space, stripped."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExamHashes:
    contexts: frozenset[str]
    questions: frozenset[str]
    generators: dict[str, str]

    def matches(self, context: str, question: str) -> str | None:
        """Why this text is refused ("context" / "question"), or None."""
        if text_hash(context) in self.contexts:
            return "context"
        if text_hash(question) in self.questions:
            return "question"
        return None


def load_exam_hashes(path: Path = EXAM_HASHES) -> ExamHashes:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExamHashes(frozenset(data["contexts"]), frozenset(data["questions"]), data["generators"])


def _run_eval() -> Any:
    """``evals/independent/run_eval.py``, for its sha256-checked generator loader."""
    if "run_eval" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "run_eval", REPO / "evals" / "independent" / "run_eval.py"
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules["run_eval"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["run_eval"]


def exam_documents(seeds: Iterable[int]) -> Iterator[tuple[str, str, int, dict[str, Any]]]:
    """(lane, size, seed, generate() output) for every active exam generator."""
    run_eval = _run_eval()
    gens = run_eval.Generators(run_eval.load_manifest())
    for lane in run_eval.LANES:
        for size in run_eval.SIZES:
            for seed in seeds:
                yield lane, size, seed, gens.get(lane).generate(seed, size)


def build_exam_hashes(seeds: Iterable[int]) -> dict[str, Any]:
    seeds = list(seeds)
    contexts: set[str] = set()
    questions: set[str] = set()
    for _lane, _size, _seed, doc in exam_documents(seeds):
        contexts.add(text_hash(doc["context"]))
        questions.add(text_hash(doc["question"]))
    manifest = _run_eval().load_manifest()
    return {
        "issue": 75,
        "what": "sha256 of normalize(text) for every active evals/independent document",
        "normalize": "NFKC, casefold, whitespace runs -> one space, strip",
        "seeds": [min(seeds), max(seeds)],
        "sizes": list(_run_eval().SIZES),
        "generators": {
            lane: g["active"]["sha256"] for lane, g in sorted(manifest["generators"].items())
        },
        "contexts": sorted(contexts),
        "questions": sorted(questions),
    }


# --- items -------------------------------------------------------------------------------


@dataclass
class Item:
    id: str
    context: str
    question: str  # question_nonthinking: answer directly after "[Answer]"
    question_thinking: str
    answer: list[str]
    language: str  # "English" | "Chinese"
    token_length: str  # the dataset's Qwen-token bucket: 8k, 16k, 32k, 64k, 128k, 256k
    primary_task: str  # "T3. Evidence-Grounded QA"
    secondary_task: str  # "T3.1 Multi-Doc Integration QA"
    contextual_requirement: str  # "Full" | "Partial"
    difficulty: str  # Easy, Moderate, Hard, Extreme
    kind: str = ""
    n_options: int = 0
    group: str = ""  # smallest item id among the items that share this document
    split: str = ""

    @property
    def task(self) -> str:
        """Primary task id, e.g. "T3"."""
        return self.primary_task.split(".", 1)[0]

    @property
    def subtask(self) -> str:
        """Secondary task id, e.g. "T3.1"."""
        return self.secondary_task.split(" ", 1)[0]

    @property
    def metric(self) -> str:
        return TASK_METRICS[self.secondary_task]

    @property
    def scorable(self) -> bool:
        return self.metric in SCORERS

    @property
    def is_mc(self) -> bool:
        return self.kind != "open"

    @property
    def chance(self) -> float | None:
        return chance(self.kind, self.n_options)

    @functools.cached_property
    def est_tokens(self) -> int:
        """Prompt estimate for context plus question (``bench.estimate_tokens``)."""
        return bench.estimate_tokens(self.context) + bench.estimate_tokens(self.question)


def item_from_record(record: dict[str, Any]) -> Item:
    missing = [f for f in FIELDS if f not in record]
    if missing:
        raise ValueError(f"LongBench Pro record {record.get('id')!r} lacks {missing}")
    if record["secondary_task"] not in TASK_METRICS:
        raise ValueError(f"unknown secondary task {record['secondary_task']!r}")
    kind, n_options = answer_kind(record["question_nonthinking"], record["answer"])
    return Item(
        id=record["id"],
        context=record["context"],
        question=record["question_nonthinking"],
        question_thinking=record["question_thinking"],
        answer=list(record["answer"]),
        language=record["language"],
        token_length=record["token_length"],
        primary_task=record["primary_task"],
        secondary_task=record["secondary_task"],
        contextual_requirement=record["contextual_requirement"],
        difficulty=record["difficulty"],
        kind=kind,
        n_options=n_options,
    )


@dataclass
class Loaded:
    items: list[Item]
    refused: list[tuple[Item, str]]  # (item, "context" | "question"): matched the exam


def load(
    path: Path = DEFAULT_PATH, *, exam: ExamHashes | None = None, verify: bool = False
) -> Loaded:
    """Every item, tagged with split and kind; items matching the exam are refused."""
    raw = path.read_bytes()
    if verify and hashlib.sha256(raw).hexdigest() != SHA256:
        raise RuntimeError(f"{path} does not match the pinned sha256 of {FILENAME}")
    return load_records(json.loads(raw), exam=exam)


def load_records(records: Iterable[dict[str, Any]], *, exam: ExamHashes | None = None) -> Loaded:
    """Tag records; groups are formed over every record, so the exam never moves a split."""
    exam = exam if exam is not None else load_exam_hashes()
    every = [item_from_record(r) for r in records]
    ids = [it.id for it in every]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate LongBench Pro ids")
    groups = document_groups(every)
    items: list[Item] = []
    refused: list[tuple[Item, str]] = []
    for item in every:
        item.group = groups[item.id]
        item.split = split_of(item.group)
        why = exam.matches(item.context, item.question)
        if why:
            refused.append((item, why))
        else:
            items.append(item)
    return Loaded(items, refused)


def select(
    items: Iterable[Item],
    *,
    split: str | None = None,
    kinds: Iterable[str] | None = None,
    tasks: Iterable[str] | None = None,
    languages: Iterable[str] | None = None,
    max_tokens: int | None = None,
    max_bucket: str | None = None,
    scorable_only: bool = True,
) -> list[Item]:
    """Filter items. ``tasks`` takes primary ("T3") or secondary ("T3.1") ids;
    ``max_tokens`` bounds the estimate, ``max_bucket`` the dataset's own bucket."""
    if max_bucket is not None and max_bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {max_bucket!r}; expected one of {', '.join(BUCKETS)}")
    if split is not None and split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {', '.join(SPLITS)}")
    kinds = set(kinds) if kinds is not None else None
    tasks = set(tasks) if tasks is not None else None
    languages = set(languages) if languages is not None else None
    return [
        it
        for it in items
        if (split is None or it.split == split)
        and (kinds is None or it.kind in kinds)
        and (tasks is None or it.task in tasks or it.subtask in tasks)
        and (languages is None or it.language in languages)
        and (not scorable_only or it.scorable)
        and (max_tokens is None or it.est_tokens <= max_tokens)
        and (max_bucket is None or BUCKETS.index(it.token_length) <= BUCKETS.index(max_bucket))
    ]


def download(dest: Path = DEFAULT_PATH, *, url: str = URL) -> Path:
    """Fetch the pinned JSON once; a file already there must match the sha256."""
    if dest.exists():
        if hashlib.sha256(dest.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError(f"{dest} exists but does not match the pinned sha256")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as resp, part.open("wb") as out:
        while chunk := resp.read(1 << 20):
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != SHA256:
        part.unlink()
        raise RuntimeError(f"download from {url} does not match the pinned sha256")
    part.replace(dest)
    return dest


# --- scoring -----------------------------------------------------------------------------
# Reimplemented from the metric definitions in the LongBench Pro paper and its evaluation
# code (github.com/caskcsg/longcontext, LongBench-Pro/modules), which carries no license,
# so nothing is copied. Same normalisation: text after the last "[Answer]" / "[答案]",
# lowercased, one answer per line, whitespace runs collapsed.

TASK_METRICS: dict[str, str] = {
    "T1.1 Global Cohesive Retrieval": "ndcg",
    "T1.2 Key-Snippet Retrieval": "ndcg",
    "T2.1 Global Timeline Reconstruction": "pairwise",
    "T2.2 Local Causal Chain Sorting": "pairwise",
    "T3.1 Multi-Doc Integration QA": "accuracy",
    "T3.2 Single-Hop Fact QA": "accuracy",
    "T4.1 Global-Coverage Constrained Summary": "summary",
    "T4.2 Query-Focused Summary": "summary",
    "T5.1 Full-Sentence Citation Alignment": "f1",
    "T5.2 Key-Statement Citation Alignment": "f1",
    "T6.1 Large-Scale Document Clustering": "subem",
    "T6.2 Targeted Subset Cluster Identification": "f1",
    "T6.3 Global Frequency Analysis": "pairwise",
    "T7.1 Global Conflict & Inconsistency Localization": "f1",
    "T7.2 Targeted Rule or Condition Violation Detection": "f1",
    "T7.3 Comprehensive Error & Anomaly Sweep": "f1",
    "T8.1 Structured Multi-Source Consistency Verification": "subem",
    "T8.2 Single-Source Targeted Aggregation": "subem",
    "T8.3 Long-Context Procedural State Tracking": "subem",
    "T9.1 Dependency-Aware Multi-Version Impact Analysis": "f1",
    "T9.2 Localized Interface Change Detection": "f1",
    "T10.1 Large-Scale In-Context Rule Induction": "subem",
    "T10.2 Targeted Example-Based Rule Induction": "subem",
    "T11.1 Long-Range Entity & Commitment Tracking": "accuracy",
    "T11.2 Short-Range Reference Resolution & State Query": "accuracy",
}
_MARKERS = ("[Answer]", "[答案]")


def answer_lines(text: str) -> list[str]:
    """The prediction as upstream reads it: after the last marker, one line each."""
    for marker in _MARKERS:
        if marker in text:
            text = text[text.rfind(marker) + len(marker) :]
            break
    return [" ".join(line.split()) for line in text.strip().lower().split("\n")]


def _keys(answer: list[str]) -> list[str]:
    return [" ".join(a.lower().split()) for a in answer]


def accuracy(answer: list[str], pred: list[str]) -> float:
    """First line equals the first key."""
    return float(bool(answer and pred) and _keys(answer)[0] == pred[0])


def subem(answer: list[str], pred: list[str]) -> float:
    """Fraction of keys that appear as a whole line of the prediction."""
    keys = _keys(answer)
    if not keys or not pred:
        return 0.0
    return sum(k in pred for k in keys) / len(keys)


def f1(answer: list[str], pred: list[str]) -> float:
    """Set F1 between key lines and predicted lines."""
    keys, got = set(_keys(answer)), set(pred)
    common = len(keys & got)
    if not common:
        return 0.0
    precision, recall = common / len(got), common / len(keys)
    return 2 * precision * recall / (precision + recall)


def pairwise(answer: list[str], pred: list[str]) -> float:
    """Ordered key pairs that the prediction also orders, over all predicted pairs."""
    keys = _keys(answer)
    if len(keys) < 2 or len(pred) < 2:
        return 0.0
    position = {p: i for i, p in enumerate(pred)}  # a repeated line keeps its last place
    total = len(pred) * (len(pred) - 1) // 2
    right = sum(
        1
        for a, b in itertools.combinations(keys, 2)
        if a in position and b in position and position[a] < position[b]
    )
    return right / total


def ndcg(answer: list[str], pred: list[str]) -> float:
    """nDCG@k, k = number of keys; key i has gain k - i, the rest 0 (trec_eval style)."""
    keys = _keys(answer)
    if not keys or not pred:
        return 0.0
    k = len(keys)
    gain: dict[str, int] = {}
    for i, key in enumerate(keys):
        gain[key] = k - i  # a repeated key keeps its last (lower) gain, as a dict would
    # Upstream ranks a repeated line at its last place too, so a key that lists the same
    # entry twice still scores 1.0 against itself.
    last = {p: i for i, p in enumerate(pred)}
    ranked = sorted(last, key=last.__getitem__)[:k]
    dcg = sum(gain.get(p, 0) / math.log2(i + 2) for i, p in enumerate(ranked))
    ideal = sorted(gain.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


SCORERS = {"accuracy": accuracy, "subem": subem, "f1": f1, "pairwise": pairwise, "ndcg": ndcg}


def score(item: Item, text: str) -> bench.Scored:
    """Score ``text`` against ``item``; exact means 1.0. Summaries are left unscored."""
    return score_answer(item.secondary_task, text, item.answer)


def score_answer(secondary_task: str, text: str, answer: list[str]) -> bench.Scored:
    metric = TASK_METRICS[secondary_task]
    if metric not in SCORERS:
        return bench.Scored(0.0, None, {"metric": metric, "unscored": "needs an embedding model"})
    pred = answer_lines(text or "")
    value = SCORERS[metric](answer, pred) if (text or "").strip() else 0.0
    return bench.Scored(value, value == 1.0, {"metric": metric})


# --- the harness's question format -----------------------------------------------------------


def task_key(item: Item) -> str:
    """Name under which an item's secondary task is registered in ``bench.TASKS``."""
    return f"lbp/{item.subtask}"


def _no_build(_size: int, _seed: int) -> bench.Instance:
    raise RuntimeError("LongBench Pro items are built by longbenchpro.instance")


def register(item: Item) -> str:
    """Make the item's secondary task a bench task; returns its key."""
    key = task_key(item)
    if key not in bench.TASKS:
        secondary = item.secondary_task
        bench.TASKS[key] = bench.TaskSpec(
            key,
            "token_length",
            "accuracy",
            _no_build,
            lambda text, truth: score_answer(secondary, text, truth),
        )
    return key


def instance(item: Item, *, thinking: bool = False) -> bench.Instance:
    """A ``bench.Instance``: context, question and the answer list as truth. Upstream
    joins them as ``context + "\\n\\n\\n\\n" + question``; the harness takes them apart."""
    return bench.Instance(
        register(item),
        item.token_length,  # type: ignore[arg-type]
        0,
        item.context,
        item.question_thinking if thinking else item.question,
        item.answer,
        {"id": item.id, "split": item.split, **tags(item)},
    )


def tags(item: Item) -> dict[str, Any]:
    """The fields reports group by."""
    return {
        "task": item.task,
        "subtask": item.subtask,
        "kind": item.kind,
        "mc": item.is_mc,
        "n_options": item.n_options,
        "chance": item.chance,
        "metric": item.metric,
        "language": item.language,
        "token_length": item.token_length,
        "difficulty": item.difficulty,
        "contextual_requirement": item.contextual_requirement,
    }


# --- stats -----------------------------------------------------------------------------------

BUCKETS = ("8k", "16k", "32k", "64k", "128k", "256k")
WINDOWS = (16_384, 32_768)


def _task_order(task: str) -> int:
    return int(task[1:]) if task[1:].isdigit() else 99


def _pct(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def length_stats(items: list[Item]) -> dict[str, Any]:
    est = [it.est_tokens for it in items]
    chars = [len(it.context) for it in items]
    return {
        "n": len(items),
        "chars_median": int(statistics.median(chars)) if chars else 0,
        "est_median": int(statistics.median(est)) if est else 0,
        "est_p90": _pct(est, 0.9) if est else 0,
        "est_max": max(est, default=0),
        **{f"fit_{w // 1024}k": sum(e <= w for e in est) for w in WINDOWS},
        **{f"bucket_{w // 1024}k": sum(_bucket_tokens(it) <= w for it in items) for w in WINDOWS},
    }


def _bucket_tokens(item: Item) -> int:
    """The dataset's length bucket in tokens: "16k" -> 16,384."""
    return int(item.token_length.rstrip("k")) * 1024


def format_stats(loaded: Loaded) -> str:
    items = loaded.items
    lines = [
        f"LongBench Pro ({DATASET} @ {REVISION[:7]}): {len(items)} items in "
        f"{len({it.group for it in items})} document groups, "
        f"{len(loaded.refused)} refused as exam matches.",
        "",
        "`tok` is `bench.estimate_tokens` of context + question (one per digit, else "
        "chars/3.5): it overcounts English prose and undercounts Chinese. `fit 16k` / "
        "`fit 32k` count estimates at or under 16,384 / 32,768, before any output reserve. "
        "`bkt` counts items whose dataset bucket (Qwen tokenizer, 8k to 256k) is at most "
        "16k / 32k; a 16k item needs more than a 16K window once output is reserved.",
        "",
        "| task | kind | split | n | median chars | median tok | p90 tok | max tok "
        "| fit 16k | fit 32k | bkt 16k | bkt 32k |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple[str, str, str], list[Item]] = {}
    for it in items:
        groups.setdefault((it.task, it.kind, it.split), []).append(it)
    for task, kind, split in sorted(
        groups, key=lambda k: (_task_order(k[0]), KINDS.index(k[1]), SPLITS.index(k[2]))
    ):
        s = length_stats(groups[(task, kind, split)])
        lines.append(
            f"| {task} | {kind} | {split} | {s['n']} | {s['chars_median']:,} | "
            f"{s['est_median']:,} | {s['est_p90']:,} | {s['est_max']:,} | "
            f"{s['fit_16k']} | {s['fit_32k']} | {s['bucket_16k']} | {s['bucket_32k']} |"
        )
    lines += ["", "| kind | " + " | ".join(SPLITS) + " | total |", "|---|---|---|---|---|"]
    for kind in KINDS:
        row = [sum(it.kind == kind and it.split == sp for it in items) for sp in SPLITS]
        lines.append(f"| {kind} | " + " | ".join(map(str, row)) + f" | {sum(row)} |")
    lines += [
        "",
        "| bucket | " + " | ".join(SPLITS) + " | English | Chinese |",
        "|---|---|---|---|---|---|",
    ]
    for bucket in BUCKETS:
        row = [sum(it.token_length == bucket and it.split == sp for it in items) for sp in SPLITS]
        langs = [sum(it.token_length == bucket and it.language == lang for it in items)
                 for lang in ("English", "Chinese")]  # fmt: skip
        lines.append(f"| {bucket} | " + " | ".join(map(str, row + langs)) + " |")
    for item, why in loaded.refused:
        lines.append(f"refused {item.id} ({item.subtask}): {why} matches an exam document")
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help=f"fetch {FILENAME} at the pinned revision")
    dl.add_argument("--data", type=Path, default=DEFAULT_PATH, metavar="FILE")
    st = sub.add_parser("stats", help="counts and lengths per task, kind and split")
    st.add_argument("--data", type=Path, default=DEFAULT_PATH, metavar="FILE")
    st.add_argument("--split", choices=SPLITS, default=None)
    st.add_argument("--kinds", default=None, help="comma-separated: mc, mc-multi, open")
    st.add_argument("--max-tokens", type=int, default=None, help="drop longer estimates")
    st.add_argument("--max-bucket", choices=BUCKETS, default=None, help="drop longer buckets")
    st.add_argument("--all", action="store_true", help="include unscored T4 summaries")
    ex = sub.add_parser("exam-hashes", help="rebuild exam_hashes.json from the active exam")
    ex.add_argument("--seeds", default="0-99", help="inclusive range (default 0-99)")
    ex.add_argument("--out", type=Path, default=EXAM_HASHES, metavar="FILE")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "download":
        print(download(args.data))
        return 0
    if args.command == "exam-hashes":
        lo, _, hi = args.seeds.partition("-")
        data = build_exam_hashes(range(int(lo), int(hi or lo) + 1))
        args.out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"{args.out}: {len(data['contexts'])} contexts, {len(data['questions'])} questions")
        return 0
    if not args.data.exists():
        print(f"longbenchpro: {args.data} not found; run the download command", file=sys.stderr)
        return 2
    loaded = load(args.data)
    kinds = [k.strip() for k in args.kinds.split(",")] if args.kinds else None
    loaded.items = select(
        loaded.items,
        split=args.split,
        kinds=kinds,
        max_tokens=args.max_tokens,
        max_bucket=args.max_bucket,
        scorable_only=not args.all,
    )
    print(format_stats(loaded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
