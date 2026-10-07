"""OOLONG-lite: count support tickets per category when no keyword gives it away.

    uv run python examples/oolong_lite.py --profile pluto --tickets 300
    uv run python examples/oolong_lite.py --dump          # tickets + truth, no model

Each ticket is a paraphrase that never contains its category's words (asserted
at generation time), so regex or keyword matching cannot solve the task; the
model has to read, which means batching tickets into ``llm_query`` calls.
Score is the per-category absolute error between the model's counts and the
ground truth. ``run()`` is importable by ``eval.py``.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

from reclamo.client import LMClient
from reclamo.config import APIKeyError, ConfigError, RLMConfig, load_config, resolve_api_key
from reclamo.errors import RLMError
from reclamo.logger import TrajectoryLogger
from reclamo.rlm import RLM

CATEGORIES = ["billing", "shipping delay", "damaged item", "login problem", "feature request"]

# Words that must never appear in a ticket of ANY category (whole-word, any case).
BANNED: dict[str, list[str]] = {
    "billing": ["billing", "bill", "billed", "charge", "charged", "charges", "invoice",
                "invoiced", "refund", "refunded", "payment", "pay", "paid", "overcharged"],
    "shipping delay": ["shipping", "ship", "shipped", "shipment", "delay", "delayed", "late"],
    "damaged item": ["damaged", "damage", "broken", "broke", "item", "defective"],
    "login problem": ["login", "log", "logged", "signin", "sign", "authentication", "problem"],
    "feature request": ["feature", "features", "request", "requested", "suggest", "suggestion"],
}  # fmt: skip

TEMPLATES: dict[str, list[str]] = {
    "billing": [
        "My card statement shows {amount} taken twice for the {product} I ordered on {date}.",
        "I was debited {amount} more than the total quoted at checkout for order {order}.",
        "The receipt for order {order} lists {amount}, but the site said the {product} cost less.",
        "Why does my bank show a second withdrawal of {amount} from you dated {date}?",
        "Order {order} was cancelled on {date} yet the {amount} still left my account.",
        "The monthly amount for my plan went from {amount} to a higher figure without notice.",
        "A promo code took nothing off order {order}; I still see the full {amount} on my card.",
        "I returned the {product} on {date} and the {amount} has not come back to my account.",
        "There is a {amount} line on my statement from {date} that I do not recognise.",
        "My subscription total for {date} is {amount} but the plan page says it should be lower.",
        "The {product} was advertised at a discount, yet order {order} shows {amount}.",
        "Tax on order {order} looks wrong: the total came to {amount} for a {product}.",
        "My account was debited {amount} on {date} after I had already closed the subscription.",
        "Two separate card deductions of {amount} appeared for a single {product} purchase.",
    ],
    "shipping delay": [
        "Order {order} was due by {date} and the tracking page still says in transit.",
        "It has been {days} days since I ordered the {product} and nothing has arrived.",
        "The carrier shows order {order} sitting at the same depot since {date}.",
        "My {product} missed the promised {date} arrival and there is no new estimate.",
        "Tracking for order {order} has not updated in {days} days.",
        "Still waiting on the {product} from order {order}; the arrival estimate passed {date}.",
        "The parcel with my {product} was marked out for the courier on {date} and never came.",
        "Expected the {product} by {date}; the status has been 'label created' for {days} days.",
        "Order {order} keeps getting a new arrival date; the latest is {date}.",
        "I chose express on order {order} and {days} days on it is still not here.",
        "The {product} ordered on {date} has been stuck at customs with no movement.",
        "Can you find out where order {order} is? It should have arrived {days} days ago.",
        "No parcel yet for order {order}, and the courier has no record of picking it up.",
        "The {product} was supposed to land before {date}; the tracking number returns nothing.",
    ],
    "damaged item": [
        "The {product} arrived with a cracked casing and a dent in one corner.",
        "Opened the box for order {order} and the {product} was in pieces.",
        "My {product} from order {order} has a deep scratch across the front.",
        "The {product} showed up bent out of shape; the packaging was crushed.",
        "Order {order} arrived leaking; the {product} and the box were soaked.",
        "There is a shattered panel on the {product} I received on {date}.",
        "The {product} came with a torn seam and a missing strap.",
        "A chunk is chipped off the {product} that arrived on {date}.",
        "The box for order {order} was intact but the {product} inside is dented badly.",
        "My {product} has a split along the side and will not close.",
        "The {product} from order {order} arrived warped and does not sit flat.",
        "Received the {product} with the glass front smashed in on {date}.",
        "The courier dropped the parcel; the {product} inside now rattles and the lid is cracked.",
        "The {product} arrived scuffed all over with a bent connector.",
    ],
    "login problem": [
        "The app bounces me back to the welcome screen every time I enter my credentials.",
        "I get 'account locked' whenever I try to get into my account since {date}.",
        "My password reset link for {name}'s account expires before I can open it.",
        "The verification code never arrives on my phone, so I cannot get past the first screen.",
        "After changing my email on {date} the site no longer accepts my credentials.",
        "Two-factor keeps asking for a code from a device I no longer own.",
        "Entering my password just reloads the page without any error.",
        "I am stuck on 'session expired' no matter how many times I re-enter my details.",
        "The account for {name} says the email is unknown, but I have orders under it.",
        "Face unlock on the mobile app stopped working after the {date} update.",
        "My credentials work on the website but the app rejects them.",
        "The reset email for {name} goes to an address I cannot access anymore.",
        "Every attempt to get into my account ends with a blank page and a spinner.",
        "The site says too many attempts and will not let me in for {name}.",
    ],
    "feature request": [
        "It would be great if the dashboard could export order history as CSV.",
        "Please consider letting us schedule a {product} order ahead of time.",
        "Would love a dark mode in the mobile app.",
        "Could you let us save several delivery addresses under one profile?",
        "An option to pause a subscription for a month would be really useful.",
        "Any chance of a size guide next to each {product} on the product page?",
        "I would like to be able to gift a {product} directly from my wishlist.",
        "It would help if the app sent a push notification when a {product} is back in stock.",
        "Please add a way to compare two {product} models side by side.",
        "Could the order page show an estimated carbon footprint for each delivery?",
        "A family plan where {name} and I share one account would be ideal.",
        "It would be nice to filter reviews by verified purchase.",
        "Consider adding a one-tap wallet at checkout; many of us would use it.",
        "Would you think about offering a repair service for the {product} line?",
    ],
}

_NAMES = ["Priya", "Marcus", "Elena", "Tomas", "Aisha", "Jonah", "Mei", "Luis", "Hannah", "Omar"]
_PRODUCTS = [
    "headphones", "coffee grinder", "desk lamp", "backpack", "running shoes",
    "blender", "monitor stand", "water bottle", "keyboard", "rain jacket",
]  # fmt: skip
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class Ticket:
    id: int
    category: str
    text: str


def _fill(template: str, rng: random.Random) -> str:
    return template.format(
        name=rng.choice(_NAMES),
        product=rng.choice(_PRODUCTS),
        amount=f"${rng.randint(5, 400)}.{rng.randint(0, 99):02d}",
        date=f"{rng.choice(_MONTHS)} {rng.randint(1, 28)}",
        order=f"#{rng.randint(10000, 99999)}",
        days=rng.randint(3, 21),
    )


def ticket_text(category: str, rng: random.Random) -> str:
    """One filled-in paraphrase for ``category`` (shared with ``nested.py``)."""
    return _fill(rng.choice(TEMPLATES[category]), rng)


def _banned_pattern() -> re.Pattern[str]:
    words = {w for ws in BANNED.values() for w in ws}
    for cat in CATEGORIES:
        words.update(cat.split())
    return re.compile(r"\b(" + "|".join(sorted(map(re.escape, words))) + r")\b", re.IGNORECASE)


def check_tickets(tickets: list[Ticket]) -> None:
    """Raise if any ticket contains a category word; the task must not be greppable."""
    pattern = _banned_pattern()
    for t in tickets:
        hit = pattern.search(t.text)
        if hit:
            raise AssertionError(
                f"ticket {t.id} ({t.category}) contains banned word {hit.group(0)!r}"
            )


def generate_tickets(n: int = 300, seed: int = 0) -> tuple[list[Ticket], dict[str, int]]:
    """Return n tickets with uneven category mix, plus the exact per-category counts."""
    rng = random.Random(seed)
    weights = [rng.uniform(0.6, 1.6) for _ in CATEGORIES]
    tickets: list[Ticket] = []
    truth = dict.fromkeys(CATEGORIES, 0)
    for i in range(1, n + 1):
        category = rng.choices(CATEGORIES, weights=weights)[0]
        text = ticket_text(category, rng)
        tickets.append(Ticket(i, category, text))
        truth[category] += 1
    check_tickets(tickets)
    return tickets, truth


def build_context(tickets: list[Ticket]) -> str:
    return "\n".join(f"Ticket {t.id}: {t.text}" for t in tickets)


def build_query() -> str:
    cats = ", ".join(CATEGORIES)
    return (
        f"Each line of the context is one customer support ticket. How many tickets fall "
        f"into each of these categories: {cats}? Every ticket belongs to exactly one "
        "category. Reply with a count for every category, as 'category: count' lines."
    )


def _name_pattern(cat: str) -> re.Pattern[str]:
    name = r"[\s_-]+".join(re.escape(w) for w in cat.split())
    return re.compile(rf"\b{name}s?\b", re.IGNORECASE)


def parse_counts(answer: str, categories: list[str] = CATEGORIES) -> dict[str, int | None]:
    """Pull one integer per category out of free-form text; None when absent.

    The answer is split into clauses (on commas, newlines, semicolons, table
    cells and the word "and") so a count binds to the category in the same
    clause, whether the number comes before or after the name. This copes with
    "61 tickets about billing" and "billing: 61" alike.
    """
    found: dict[str, int | None] = dict.fromkeys(categories)
    patterns = {cat: _name_pattern(cat) for cat in categories}
    for fragment in re.split(r"[,\n;]| and ", answer):
        number = re.search(r"\d+", fragment)
        if not number:
            continue
        for cat in categories:
            if found[cat] is None and patterns[cat].search(fragment):
                found[cat] = int(number.group())
                break
    return found


def score(answer: str, truth: dict[str, int]) -> tuple[dict[str, int | None], dict[str, int], int]:
    """Return (predicted, per-category absolute error, total error)."""
    predicted = parse_counts(answer, list(truth))
    errors = {
        cat: abs((predicted[cat] if predicted[cat] is not None else 0) - truth[cat])
        for cat in truth
    }
    return predicted, errors, sum(errors.values())


def run(
    cfg: RLMConfig,
    client: Any,
    n_tickets: int = 300,
    seed: int = 0,
    *,
    log_dir: str | None = None,
) -> dict[str, Any]:
    tickets, truth = generate_tickets(n_tickets, seed)
    context = build_context(tickets)
    logger = TrajectoryLogger(log_dir)
    started = time.monotonic()
    summary: dict[str, Any] = {
        "task": "oolong_lite",
        "n_tickets": n_tickets,
        "chars": len(context),
        "truth": truth,
    }
    try:
        result = RLM(cfg, client, logger=logger).completion(context, build_query())
    except RLMError as exc:
        answer = exc.partial_answer or ""
        predicted, errors, total = score(answer, truth)
        summary.update(
            answer=answer,
            predicted=predicted,
            errors=errors,
            total_error=total,
            error=str(exc),
            turns=None,
            subcalls=None,
            tokens=None,
            elapsed=round(time.monotonic() - started, 2),
            stop_reason="error",
            trajectory=str(logger.path) if logger.path else None,
        )
        return summary
    predicted, errors, total = score(result.answer, truth)
    summary.update(
        answer=result.answer,
        predicted=predicted,
        errors=errors,
        total_error=total,
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
    parser.add_argument("--tickets", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--log-dir", default="runs")
    parser.add_argument("--dump", action="store_true", help="print tickets and truth; no model")
    args = parser.parse_args(argv)

    if args.dump:
        tickets, truth = generate_tickets(args.tickets, args.seed)
        print(build_context(tickets))
        print()
        print("truth:", ", ".join(f"{cat}={n}" for cat, n in truth.items()))
        return 0

    try:
        cfg, client = build_client(args.profile, args.profiles)
    except (ConfigError, APIKeyError) as exc:
        print(f"oolong_lite: {exc}", file=sys.stderr)
        return 2
    summary = run(cfg, client, args.tickets, args.seed, log_dir=args.log_dir)
    print(f"answer:      {summary['answer']!r}")
    print(f"truth:       {summary['truth']}")
    print(f"predicted:   {summary['predicted']}")
    print(f"errors:      {summary['errors']}")
    print(f"total error: {summary['total_error']}")
    print(f"turns:       {summary['turns']}")
    print(f"sub-calls:   {summary['subcalls']}")
    print(f"tokens:      {summary['tokens']}")
    print(f"elapsed:     {summary['elapsed']}s")
    if summary.get("error"):
        print(f"error:       {summary['error']}", file=sys.stderr)
    return 0 if summary["total_error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
