"""Long-document QA: two-hop questions over a long synthetic engineering digest.

    uv run python examples/longdoc_qa.py --profile pluto --sections 60
    uv run python examples/longdoc_qa.py --dump --sections 10     # document + answers, no model

The document is a run of weekly digests. Each project has exactly one *owner*
sentence and each person exactly one *office* sentence, placed in sections far
apart from each other, among many distractor sentences that mention the same
project (reviews, demos, deputies) or the same person with other cities
(home town, university, a trip). A question asks for the office city of the
person who owns a project, so answering needs two hops and reading, not one
regex: a project's codename and its owner's office city never share a
sentence (asserted at generation time). Answers are exact-match on the city.
``run()`` is importable by ``bench.py``.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from reclamo.client import LMClient
from reclamo.config import APIKeyError, ConfigError, RLMConfig, load_config, resolve_api_key
from reclamo.errors import RLMError
from reclamo.logger import TrajectoryLogger
from reclamo.rlm import RLM

CITIES = [
    "Lisbon", "Oslo", "Nairobi", "Montreal", "Kyoto", "Austin", "Dublin", "Zurich",
    "Santiago", "Perth", "Helsinki", "Jakarta", "Denver", "Porto", "Tallinn", "Lima",
    "Omaha", "Bergen", "Valencia", "Adelaide", "Krakow", "Bogota", "Seattle", "Dakar",
]  # fmt: skip

CODENAMES = [
    "CASCADE", "BRINDLE", "TOPAZ", "MARLIN", "SUNDIAL", "PEWTER", "CALDERA", "ORIOLE",
    "GARNET", "HALYARD", "TURBINE", "MOSAIC", "FJORD", "KINDLE", "SEXTANT", "PARAGON",
    "CITADEL", "LUMEN", "ARBOR", "VESPER", "NIMBUS", "SPINDLE", "ALCOVE", "BEACON",
    "COBALT", "DRIFTWOOD", "EMBERLY", "FOXGLOVE", "GRISTLE", "HOLLOW", "INKWELL", "JUBILEE",
]  # fmt: skip

_FIRST = [
    "Priya", "Marcus", "Elena", "Tomas", "Aisha", "Jonah", "Mei", "Luis", "Hannah", "Omar",
    "Sofia", "Daniel", "Ingrid", "Kwame", "Yuki", "Rafael", "Noor", "Felix", "Amara", "Viktor",
]  # fmt: skip
_LAST = [
    "Natarajan", "Oyelaran", "Vasquez", "Lindqvist", "Okafor", "Brennan", "Takahashi", "Moreau",
    "Schneider", "Haddad", "Castellano", "Petrov", "Nakamura", "Mensah", "Fitzgerald", "Duarte",
]  # fmt: skip
_TEAMS = ["platform", "payments", "growth", "data", "reliability", "mobile", "security"]
_THEMES = [
    "release readiness", "incident review", "capacity planning", "hiring update",
    "cost review", "roadmap check-in", "vendor evaluation", "on-call handover",
    "migration status", "quality metrics", "customer escalations", "tooling",
]  # fmt: skip

# The one sentence per project that answers "who owns it".
OWNER_TEMPLATES = [
    "{person} is the accountable owner of {project}.",
    "Day-to-day ownership of {project} sits with {person}.",
    "{project} is run by {person}, who signs off on every release.",
    "Ownership of {project} was confirmed as {person}.",
]
# The one sentence per person that answers "where is their office".
OFFICE_TEMPLATES = [
    "{person} works out of the {city} office.",
    "{person}'s desk is in the {city} office.",
    "{person} is based at the {city} site.",
    "The {city} office is where {person} sits.",
]
# Distractors: same project, other roles.
PROJECT_DISTRACTORS = [
    "{person} reviewed the test plan for {project}.",
    "{person} presented the latest numbers for {project} at the all-hands.",
    "{person} is the deputy on {project} and covers when the owner is out.",
    "{person} filed three bugs against {project} this week.",
    "{person} asked for a budget line for {project} next quarter.",
    "{project} is sponsored by the {team} group.",
    "The {team} group paired with {person} on {project} documentation.",
    "{project} slipped by {days} days; {person} will present the recovery plan.",
]
# Distractors: same person, other cities.
PERSON_DISTRACTORS = [
    "{person} grew up in {city}.",
    "{person} studied engineering in {city}.",
    "{person} flew to {city} for the vendor summit.",
    "{person} will be on leave visiting family in {city}.",
    "{person} ran the {city} marathon last spring.",
]
FILLER = [
    "Error budget for the {team} group stands at {pct} percent for the month.",
    "The {team} group closed {n} tickets and opened {m}.",
    "Build times on the main pipeline dropped to {n} minutes after the cache change.",
    "Two flaky integration tests were quarantined pending a fix.",
    "The weekly on-call summary lists {n} pages, none customer-facing.",
    "Headcount for the {team} group is unchanged at {n}.",
    "The {team} group's dashboard migration is {pct} percent complete.",
    "Vendor invoices for the quarter total {amount}.",
    "A postmortem for last week's queue backlog is scheduled for {day}.",
    "The {team} group reports {n} open vulnerabilities, all low severity.",
    "Storage growth is tracking at {n} GB per week.",
    "The design review calendar is full until {day}.",
    "Latency at the 99th percentile is {n} ms, inside the target.",
    "The {team} group rotated its on-call lead this week.",
]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

_ANSWER_LINE = re.compile(r"^\s*(?:q(?:uestion)?\s*)?(\d+)\s*[:.)\-–]\s*(.+?)\s*$", re.I)


@dataclass(frozen=True)
class Question:
    number: int
    text: str
    answer: str
    project: str
    person: str


@dataclass
class Document:
    text: str
    questions: list[Question]
    owners: dict[str, str]  # project -> person
    offices: dict[str, str]  # person -> city
    sections: int
    placement: dict[str, tuple[int, int]] = field(default_factory=dict)  # project -> (s_own, s_off)


def _people(rng: random.Random, n: int) -> list[str]:
    pool = [f"{f} {last}" for f in _FIRST for last in _LAST]
    return rng.sample(pool, n)


def _other_city(rng: random.Random, exclude: set[str]) -> str:
    return rng.choice([c for c in CITIES if c not in exclude])


def generate_document(sections: int = 60, seed: int = 0, n_questions: int = 3) -> Document:
    """Build a deterministic document of ``sections`` weekly digests plus its questions."""
    if sections < 4:
        raise ValueError("sections must be >= 4")
    rng = random.Random(seed)
    n_projects = min(len(CODENAMES), max(n_questions, 5, sections // 4))
    projects = rng.sample(CODENAMES, n_projects)
    people = _people(rng, n_projects + 6)
    owners = dict(zip(projects, rng.sample(people, n_projects), strict=True))  # one each
    offices = {person: rng.choice(CITIES) for person in people}

    per_section: list[list[str]] = [[] for _ in range(sections)]
    placement: dict[str, tuple[int, int]] = {}
    min_gap = max(1, sections // 5)
    for project in projects:
        owner = owners[project]
        s_own = rng.randrange(sections)
        far = [s for s in range(sections) if abs(s - s_own) >= min_gap]
        s_off = rng.choice(far)
        placement[project] = (s_own, s_off)
        per_section[s_own].append(rng.choice(OWNER_TEMPLATES).format(person=owner, project=project))
    # One office sentence per person, in the section chosen for their first project
    # (or anywhere, for people who own nothing).
    office_section: dict[str, int] = {}
    for project in projects:
        owner = owners[project]
        office_section.setdefault(owner, placement[project][1])
    for person in people:
        s = office_section.get(person, rng.randrange(sections))
        per_section[s].append(
            rng.choice(OFFICE_TEMPLATES).format(person=person, city=offices[person])
        )

    for s in range(sections):
        n_distractors = rng.randint(2, 4)
        for _ in range(n_distractors):
            project = rng.choice(projects)
            if rng.random() < 0.5:
                # Never the owner: the owner sentence must stay the only project+owner pair.
                per_section[s].append(
                    rng.choice(PROJECT_DISTRACTORS).format(
                        person=rng.choice([p for p in people if p != owners[project]]),
                        project=project,
                        team=rng.choice(_TEAMS),
                        days=rng.randint(2, 9),
                    )
                )
            else:
                person = rng.choice(people)
                per_section[s].append(
                    rng.choice(PERSON_DISTRACTORS).format(
                        person=person, city=_other_city(rng, {offices[person]})
                    )
                )
        for _ in range(rng.randint(5, 7)):
            per_section[s].append(
                rng.choice(FILLER).format(
                    team=rng.choice(_TEAMS),
                    pct=rng.randint(40, 99),
                    n=rng.randint(3, 240),
                    m=rng.randint(3, 60),
                    amount=f"${rng.randint(10, 900)},{rng.randint(100, 999)}",
                    day=rng.choice(_DAYS),
                )
            )
        rng.shuffle(per_section[s])

    parts = []
    for s, sentences in enumerate(per_section, 1):
        parts.append(f"## Week {s} digest: {rng.choice(_THEMES)}\n" + " ".join(sentences))
    text = "\n\n".join(parts)

    asked = rng.sample(projects, n_questions)
    questions = [
        Question(
            number=i,
            text=f"In which city is the office of the person who owns project {p}?",
            answer=offices[owners[p]],
            project=p,
            person=owners[p],
        )
        for i, p in enumerate(asked, 1)
    ]
    doc = Document(text, questions, owners, offices, sections, placement)
    check_document(doc)
    return doc


def check_document(doc: Document) -> None:
    """Raise if a question could be answered by one regex (project and city co-occur)."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", doc.text)
    for q in doc.questions:
        pattern = re.compile(rf"\b{re.escape(q.project)}\b.*\b{re.escape(q.answer)}\b|"
                             rf"\b{re.escape(q.answer)}\b.*\b{re.escape(q.project)}\b")  # fmt: skip
        for sentence in sentences:
            if pattern.search(sentence):
                raise AssertionError(
                    f"question {q.number}: {q.project!r} and {q.answer!r} share a sentence"
                )
        s_own, s_off = doc.placement[q.project]
        if s_own == s_off:
            raise AssertionError(f"question {q.number}: owner and office in the same section")


def build_query(questions: list[Question]) -> str:
    numbered = "\n".join(f"{q.number}. {q.text}" for q in questions)
    return (
        "The context is a long engineering digest. Answer each question below with the "
        "city name only. Every project has exactly one owner and every person has exactly "
        "one office; other cities mentioned near a person are not their office.\n\n"
        f"{numbered}\n\nReply with one line per question, in the form `<number>: <city>`."
    )


def parse_answers(answer: str, n: int) -> dict[int, str]:
    """Map question number -> answer text. A lone unnumbered reply counts for question 1."""
    found: dict[int, str] = {}
    for line in answer.splitlines():
        m = _ANSWER_LINE.match(line)
        if m:
            number = int(m.group(1))
            if 1 <= number <= n and number not in found:
                found[number] = m.group(2)
    if not found and n == 1 and answer.strip():
        found[1] = answer.strip()
    return found


def _city_pattern(city: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(city)}\b", re.IGNORECASE)


def is_correct(text: str, truth: str) -> bool:
    """Exact-match on the city: the truth is present and no other city from the pool is."""
    if not _city_pattern(truth).search(text):
        return False
    return not any(_city_pattern(c).search(text) for c in CITIES if c != truth)


def score(answer: str, questions: list[Question]) -> tuple[list[bool], float]:
    """Return (per-question correctness, fraction correct)."""
    parsed = parse_answers(answer, len(questions))
    marks = [is_correct(parsed.get(q.number, ""), q.answer) for q in questions]
    return marks, (sum(marks) / len(marks) if marks else 0.0)


def run(
    cfg: RLMConfig,
    client: Any,
    sections: int = 60,
    seed: int = 0,
    *,
    n_questions: int = 3,
    log_dir: str | None = None,
) -> dict[str, Any]:
    doc = generate_document(sections, seed, n_questions)
    query = build_query(doc.questions)
    logger = TrajectoryLogger(log_dir)
    started = time.monotonic()
    summary: dict[str, Any] = {
        "task": "longdoc_qa",
        "sections": sections,
        "chars": len(doc.text),
        "questions": [q.text for q in doc.questions],
        "truth": [q.answer for q in doc.questions],
    }
    try:
        result = RLM(cfg, client, logger=logger).completion(doc.text, query)
    except RLMError as exc:
        answer = exc.partial_answer or ""
        marks, fraction = score(answer, doc.questions)
        summary.update(
            answer=answer,
            correct=marks,
            score=fraction,
            error=str(exc),
            turns=None,
            subcalls=None,
            tokens=None,
            elapsed=round(time.monotonic() - started, 2),
            stop_reason="error",
            trajectory=str(logger.path) if logger.path else None,
        )
        return summary
    marks, fraction = score(result.answer, doc.questions)
    summary.update(
        answer=result.answer,
        correct=marks,
        score=fraction,
        turns=result.iterations,
        subcalls=result.subcalls,
        tokens=result.usage.total_tokens,
        elapsed=round(result.elapsed, 2),
        stop_reason=result.stop_reason,
        trajectory=result.trajectory_path,
    )
    return summary


def build_client(profile: str, profiles: str | None) -> tuple[RLMConfig, LMClient]:
    cfg = load_config(profile, profiles)
    return cfg, LMClient(cfg, resolve_api_key(cfg))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="pluto")
    parser.add_argument("--profiles", default=None, metavar="FILE")
    parser.add_argument("--sections", type=int, default=60)
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--log-dir", default="runs")
    parser.add_argument("--dump", action="store_true", help="print document and answers; no model")
    args = parser.parse_args(argv)

    if args.dump:
        doc = generate_document(args.sections, args.seed, args.questions)
        print(doc.text)
        print()
        print(build_query(doc.questions))
        print()
        for q in doc.questions:
            print(f"answer {q.number}: {q.answer} ({q.project} -> {q.person})")
        return 0

    try:
        cfg, client = build_client(args.profile, args.profiles)
    except (ConfigError, APIKeyError) as exc:
        print(f"longdoc_qa: {exc}", file=sys.stderr)
        return 2
    summary = run(
        cfg, client, args.sections, args.seed, n_questions=args.questions, log_dir=args.log_dir
    )
    print(f"answer:    {summary['answer']!r}")
    print(f"truth:     {summary['truth']}")
    print(f"correct:   {summary['correct']}")
    print(f"score:     {summary['score']:.2f}")
    print(f"turns:     {summary['turns']}")
    print(f"sub-calls: {summary['subcalls']}")
    print(f"tokens:    {summary['tokens']}")
    print(f"elapsed:   {summary['elapsed']}s")
    if summary.get("error"):
        print(f"error:     {summary['error']}", file=sys.stderr)
    return 0 if summary["score"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
