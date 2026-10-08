"""Independent long-context freight reconciliation benchmark. Python 3.11.

Why keyword search, regex extraction, or surface counting is insufficient:
every shipment has both provisional and authoritative descriptions. Positive
and negative words occur in both, including references to irrelevant samples.
A solver must resolve nicknames, former/latter references, personnel joins,
contract-specific Boolean conditions, and explicit corrections before doing
weighted aggregation. No passage contains the requested office totals.

A purpose-built semantic parser could solve this task; that is legitimate.
The benchmark does not claim that programmatic reasoning is impossible.
"""

import json
import random
import re
from decimal import Decimal, InvalidOperation


OFFICES = (
    "Alderwick", "Brindleford", "Cairnstead", "Dunmere",
    "Elmbridge", "Fenhurst", "Gorsehaven",
)

CONTACTS = (
    "Ada Mercer", "Basil Kent", "Cora Wells", "Damon Price",
    "Elena Shaw", "Felix Reed", "Greta Moss", "Hector Lane",
    "Iona West", "Jonah Pike", "Kira Holt", "Leon Vale",
    "Mara Frost", "Nolan Beck", "Orla Finch", "Pavel Stone",
    "Quinn Marsh", "Rhea Brooks", "Soren Dale", "Tessa Wood",
    "Una Hale", "Victor Ross", "Willa Ford", "Yuri Nash",
)

MANAGERS = (
    "Amira Bell", "Brennan Cole", "Celia Drake", "Dorian Ellis",
    "Estelle Gray", "Florian Hayes", "Gillian Irwin", "Hadrian Jones",
    "Imogen Keene", "Julian Lowe", "Karina North", "Lucian Owen",
)

CALLSIGNS = (
    "Amber Kite", "Blue Lantern", "Copper Finch", "Dawn Anchor",
    "Evening Fox", "Frost Compass", "Golden Otter", "Harbor Moon",
    "Ivory Sparrow", "Jade Beacon", "Kestrel Bell", "Lilac Bridge",
    "Maple Crown", "Northern Wren", "Opal Sail", "Pearl Badger",
    "Quiet Falcon", "Red Willow", "Silver Heron", "Teal Window",
    "Umber Star", "Violet Gate", "White Raven", "Yellow Harbor",
)

CONTRACTS = (
    "Ashglass", "Birchstone", "Cloudweave", "Dewceramic", "Embercloth",
    "Flintpaper", "Glimmerwood", "Heathersteel", "Irisfiber",
)

ADJECTIVES = (
    "amber ancient autumn azure black blue brass bright bronze calm "
    "cedar chalk clear cobalt copper coral crimson crystal dark dawn "
    "distant dusk emerald evening faded fern golden granite green grey "
    "hidden hollow indigo ivory jade lilac linen lunar maple marble "
    "misty moss narrow navy ochre olive opal pale pearl pine plum quiet "
    "red rose round ruby silver slate snowy soft stone teal violet white "
    "wild winter wooden yellow"
).split()

NOUNS = (
    "anchor arch badger basket beacon bell birch boat bridge brook "
    "candle canyon castle cedar circle cloud compass crane crown dale "
    "deer doorway dove elm falcon feather fern field finch flute forest "
    "fox garden gate gull harbor hawk heron hill island kite lake "
    "lantern lark leaf lily maple meadow mill moon oak orchard otter "
    "owl pebble pier pine pond raven reed ridge river robin sail shell "
    "sparrow spring star stone swan tower valley waterfall wheel willow "
    "window wing wolf wren"
).split()

TARGETS = {"small": 60_000, "medium": 300_000, "large": 1_200_000}

SECTION_TITLES = (
    "Personnel desk: provisional directory",
    "Commercial desk: original agreements",
    "Booking correspondence",
    "Laboratory desk: preliminary reports",
    "Carrier desk: provisional custody reports",
    "Laboratory desk: signed replacement findings",
    "Accounts desk: final quantity and responsibility reconciliations",
    "Personnel and commercial desks: closing corrections",
    "Carrier desk: signed final custody audits",
)

INTRO = """Freight cooperative — May closing correspondence

The closing date is 31 May. This packet contains provisional records followed
by signed corrections. All money-like amounts below are integer credit units.

Closing instructions:
* Each docket is one shipment. Its quoted nickname identifies the same shipment
  wherever that nickname appears. Names and nicknames are exact identifiers.
* Use the signed replacement laboratory finding for both tests and the seal.
  It replaces the entire preliminary laboratory report for that shipment.
  "Passed", "met the limit", and equivalent language mean success; a failure
  means the test did not satisfy its requirement.
* Each agreement specifies whether BOTH tests, AT LEAST ONE test, or EXACTLY
  ONE test must succeed. Apply its closing amendment, including its final rate,
  allowance, and treatment of packaging waivers.
* Packaging is acceptable if the shipment's own seal was intact, OR if a waiver
  was actually signed AND the agreement permits waivers. Permission to use a
  waiver does not itself establish that a waiver was signed.
* The signed final carrier audit alone determines custody at closing. Credit
  requires that the consignee retained the shipment at closing. Earlier
  deliveries, returns, plans, and reports about other crates do not decide it.
* Use final reconciled shipped units and damaged units. For an eligible shipment,
  credited units are max(shipped minus damaged minus the agreement allowance, 0).
  Its credit is credited units multiplied by the final agreement rate.
  Ineligible shipments contribute zero. There are no other fees or credits.
* The final accounts reconciliation names the responsible contact by radio name.
  Join that radio name through the personnel directory to a person, then through
  the closing personnel correction to that person's manager, then through the
  manager's closing office correction to an office. This closing chain controls
  attribution even if a shipment was handled elsewhere earlier in the month.
* Every signed closing correction in this packet applies to the whole May
  closing. These are the only revisions; there are no ties in authority.
  Reserve contacts, relief managers, training crates, and unsigned proposals
  are not authoritative.

The requested result is the sum of shipment credits for each closing office.
"""


def _different(rng, values, old):
    return rng.choice([value for value in values if value != old])


def _test_statement(rng, test, passed):
    if passed:
        options = (
            f"The {test} trial met its contractual limit.",
            f"No failure remained in the signed {test} finding; it passed.",
            f"The allegation that {test} failed was withdrawn; success stands.",
            f"For {test}, the final verdict is satisfactory.",
        )
    else:
        options = (
            f"The {test} trial failed its contractual limit.",
            f"The claimed success in {test} was rejected; failure stands.",
            f"It would be incorrect to mark {test} as passed; it did not pass.",
            f"For {test}, the signed verdict is unsatisfactory.",
        )
    return rng.choice(options)


def _seal_statement(rng, intact):
    if intact:
        return rng.choice((
            "The dispatched crate's seal remained intact; the broken strap "
            "belonged to a training tote.",
            "The inspector withdrew the damage claim about the shipment's "
            "seal. That seal was unbroken.",
            "The sample box and dispatched crate were checked separately. "
            "The former had a torn seal; the latter did not.",
        ))
    return rng.choice((
        "The dispatched crate's seal was broken; the intact seal belonged "
        "to a training tote.",
        "The inspector withdrew the intact-seal claim about the shipment. "
        "Its own seal had been breached.",
        "The sample box and dispatched crate were checked separately. "
        "The former had an intact seal; the latter did not.",
    ))


def _gate_text(rng, gate):
    choices = {
        "both": (
            "Both moisture and vibration must succeed.",
            "A success in only one trial is insufficient; each must pass.",
            "Neither trial may fail: moisture and vibration are both required.",
        ),
        "either": (
            "At least one of moisture and vibration must succeed.",
            "One successful trial suffices, and two successes are also accepted.",
            "Reject only the combination in which neither trial passes.",
        ),
        "xor": (
            "Exactly one of moisture and vibration must succeed.",
            "The results must disagree: one success and one failure.",
            "Two successes are no more acceptable than two failures; "
            "one trial must pass and the other fail.",
        ),
    }
    return rng.choice(choices[gate])


def _waiver_text(allowed):
    if allowed:
        return (
            "A signed packaging waiver may excuse a broken seal; "
            "an unsigned request may not."
        )
    return (
        "Even a signed packaging waiver cannot excuse a broken seal "
        "under this agreement."
    )


def _quality(gate, moisture, vibration):
    if gate == "both":
        return moisture and vibration
    if gate == "either":
        return moisture or vibration
    return moisture != vibration


def generate(seed: int, size: str) -> dict:
    """Return deterministic prose, question, computed truth, and metadata."""
    if size not in TARGETS:
        raise ValueError("size must be 'small', 'medium', or 'large'")

    rng = random.Random(seed)
    sections = [[] for _ in SECTION_TITLES]
    gates = ("both", "either", "xor")

    radio_names = list(CALLSIGNS)
    rng.shuffle(radio_names)
    radio_to_person = dict(zip(radio_names, CONTACTS))
    person_to_radio = {person: radio for radio, person in radio_to_person.items()}

    initial_managers = {person: rng.choice(MANAGERS) for person in CONTACTS}
    final_managers = {
        person: (
            _different(rng, MANAGERS, initial_managers[person])
            if rng.random() < 0.70 else initial_managers[person]
        )
        for person in CONTACTS
    }
    initial_offices = {manager: rng.choice(OFFICES) for manager in MANAGERS}
    final_offices = {
        manager: (
            _different(rng, OFFICES, initial_offices[manager])
            if rng.random() < 0.70 else initial_offices[manager]
        )
        for manager in MANAGERS
    }

    for person in CONTACTS:
        manager = initial_managers[person]
        relief = _different(rng, MANAGERS, manager)
        radio = person_to_radio[person]
        if rng.randrange(2):
            text = (
                f"Directory card for {person}: radio name “{radio}”. "
                f"{manager} and {relief} appear on the escalation card. "
                "The former is the provisional line manager; the latter "
                "only supplies relief cover."
            )
        else:
            text = (
                f"Calls to “{radio}” reach {person}. The directory lists "
                f"{relief} for relief cover and {manager} for line management. "
                "The latter controls provisional accounting attribution."
            )
        sections[0].append(text)

        final = final_managers[person]
        alternate = _different(rng, MANAGERS, final)
        if rng.randrange(2):
            text = (
                f"Signed personnel correction — {person}. For the May closing, "
                f"the line manager is {final}, not {alternate}. Any earlier "
                "directory assignment is superseded. Relief cover does not "
                "confer accounting responsibility."
            )
        else:
            text = (
                f"Closing personnel review for {person}: the candidates were "
                f"{alternate} and {final}. The former was not appointed; "
                "the latter is the line manager for the entire closing. "
                "Replace the provisional assignment."
            )
        sections[7].append(text)

    for manager in MANAGERS:
        initial = initial_offices[manager]
        final = final_offices[manager]
        other = _different(rng, OFFICES, final)
        sections[0].append(
            f"Office register: {manager}'s provisional accounting office is "
            f"{initial}. Travel arrangements do not change that registration."
        )
        if rng.randrange(2):
            text = (
                f"Signed office correction for {manager}: use {final} for "
                f"May closing attribution. The suggested move to {other} "
                "was not approved. Replace the provisional office entry."
            )
        else:
            text = (
                f"The closing registration for {manager} considered {other} "
                f"and {final}. Only the latter was approved. This registration "
                "supersedes the earlier office register for all May credits."
            )
        sections[7].append(text)

    contracts = {}
    for name in CONTRACTS:
        initial = {
            "gate": rng.choice(gates),
            "rate": rng.randint(2, 13),
            "allowance": rng.randint(0, 8),
            "waivers": bool(rng.getrandbits(1)),
        }
        final = {
            "gate": _different(rng, gates, initial["gate"]),
            "rate": _different(rng, tuple(range(2, 14)), initial["rate"]),
            "allowance": _different(
                rng, tuple(range(9)), initial["allowance"]
            ),
            "waivers": not initial["waivers"],
        }
        contracts[name] = final
        sections[1].append(
            f"Original {name} agreement, circulated before closing. "
            f"{_gate_text(rng, initial['gate'])} "
            f"The rate is {initial['rate']} credits for each credited unit; "
            f"the allowance is {initial['allowance']} units per shipment. "
            f"{_waiver_text(initial['waivers'])}"
        )
        sections[7].append(
            f"Signed closing amendment to {name}. Replace the original "
            f"quality clause: {_gate_text(rng, final['gate'])} "
            f"The allowance becomes {final['allowance']} units per shipment, "
            f"and the rate becomes {final['rate']} credits per credited unit. "
            f"{_waiver_text(final['waivers'])} All four terms in this amendment "
            "apply to every May shipment under this agreement."
        )

    nicknames = [f"{a} {n}" for a in ADJECTIVES for n in NOUNS]
    rng.shuffle(nicknames)
    used_dockets = set()
    cases = []

    def render():
        parts = [INTRO.strip()]
        for title, paragraphs in zip(SECTION_TITLES, sections):
            parts.append(title + "\n\n" + "\n\n".join(paragraphs))
        return "\n\n".join(parts)

    estimated_length = len(render())
    while estimated_length < TARGETS[size]:
        if len(cases) >= len(nicknames):
            raise RuntimeError("Nickname pool exhausted")
        number = rng.randrange(100000, 1000000)
        while number in used_dockets:
            number = rng.randrange(100000, 1000000)
        used_dockets.add(number)
        docket = f"FR-{number}"
        nickname = nicknames[len(cases)]

        initial_person = rng.choice(CONTACTS)
        final_person = rng.choice(CONTACTS)
        contract_name = rng.choice(CONTRACTS)
        reserve_contract = _different(rng, CONTRACTS, contract_name)
        waiver_signed = bool(rng.getrandbits(1))

        old_units = rng.randint(25, 180)
        old_damage = rng.randint(0, 18)
        final_units = rng.randint(25, 180)
        final_damage = rng.randint(0, min(24, final_units))

        old_moisture = bool(rng.getrandbits(1))
        old_vibration = bool(rng.getrandbits(1))
        old_seal = bool(rng.getrandbits(1))
        moisture = bool(rng.getrandbits(1))
        vibration = bool(rng.getrandbits(1))
        seal = bool(rng.getrandbits(1))
        retained = bool(rng.getrandbits(1))
        initially_retained = bool(rng.getrandbits(1))

        paragraphs = []

        if rng.randrange(2):
            agreement = (
                f"Sales compared {contract_name} with {reserve_contract}; "
                "the former was executed and the latter was merely a quote."
            )
        else:
            agreement = (
                f"The unaccepted quote was {reserve_contract}. "
                f"The shipment was booked under {contract_name}."
            )
        if waiver_signed:
            waiver = rng.choice((
                "The packaging waiver was signed, rather than merely requested.",
                "A signed packaging waiver is in the booking envelope.",
                "The claim that nobody signed the packaging waiver is false; "
                "the signed copy is attached.",
            ))
        else:
            waiver = rng.choice((
                "A packaging waiver was requested but never signed.",
                "No signed packaging waiver exists for this shipment.",
                "The supposed signed packaging waiver was only an unsigned draft.",
            ))
        booking = (
            f"Booking letter — {docket}, known to the carrier as “{nickname}”. "
            f"The opening contact was “{person_to_radio[initial_person]}”. "
            f"{agreement} The provisional quantity was {old_units} units. "
            f"{waiver} The agreement choice and waiver signature status in "
            "this letter are final; quantities and responsibility await closing."
        )
        paragraphs.append((2, booking))

        preliminary = (
            f"Preliminary laboratory note for “{nickname}”. "
            f"{_test_statement(rng, 'moisture', old_moisture)} "
            f"{_test_statement(rng, 'vibration', old_vibration)} "
            f"{_seal_statement(rng, old_seal)} "
            "These findings await the signed replacement report."
        )
        paragraphs.append((3, preliminary))

        if initially_retained:
            custody = (
                "The depot's preliminary understanding was that the consignee "
                "still held the goods. A return was discussed but not yet booked."
            )
        else:
            custody = (
                "The depot's preliminary understanding was that the consignee "
                "had returned the goods. A renewed delivery was being discussed."
            )
        provisional = (
            f"Carrier message concerning {docket}. {custody} "
            f"The opening damage estimate was {old_damage} units. "
            "The dispatch board also lists a training crate; its movements "
            "must not be charged to this docket."
        )
        paragraphs.append((4, provisional))

        order = [("moisture", moisture), ("vibration", vibration)]
        rng.shuffle(order)
        first, second = order
        first_result = rng.choice(
            ("passed", "met its limit") if first[1]
            else ("failed", "did not meet its limit")
        )
        second_result = rng.choice(
            ("passed", "met its limit") if second[1]
            else ("failed", "did not meet its limit")
        )
        replacement = (
            f"Signed replacement laboratory report — {docket}. "
            f"The {first[0]} and {second[0]} trials were reconsidered in that "
            f"order. The former {first_result}; the latter {second_result}. "
            f"{_seal_statement(rng, seal)} This replaces the entire preliminary "
            "report, including its seal finding."
        )
        paragraphs.append((5, replacement))

        final_radio = person_to_radio[final_person]
        reserve_radio = _different(rng, radio_names, final_radio)
        if rng.randrange(2):
            responsibility = (
                f"“{final_radio}” and “{reserve_radio}” were proposed as "
                "responsible contact and reserve respectively. The former "
                "accepted responsibility; the latter remains reserve."
            )
        else:
            responsibility = (
                f"“{reserve_radio}” was considered before “{final_radio}”. "
                "The first was declined; the second is the responsible contact."
            )
        if rng.randrange(2):
            quantities = (
                f"The signed shipped quantity is {final_units} units, "
                f"of which {final_damage} are damaged."
            )
        else:
            quantities = (
                f"The damaged portion is {final_damage} units within a total "
                f"shipped quantity of {final_units}; it is not an additional "
                "quantity to subtract twice."
            )
        reconciliation = (
            f"Final accounts reconciliation for “{nickname}”. "
            f"{quantities} Replace all earlier quantity and damage estimates. "
            f"{responsibility} This responsibility assignment replaces the "
            "booking contact. Use the contact's closing management chain."
        )
        paragraphs.append((6, reconciliation))

        if retained:
            ending = rng.choice((
                "A return receipt was filed against this docket in error; "
                "it belonged to the training crate. The actual shipment "
                "remained with the consignee at closing.",
                "The shipment came back briefly, then was delivered again. "
                "The consignee retained it through closing; no later return "
                "occurred.",
                "The proposed collection was canceled before it happened. "
                "At closing the consignee still held the shipment.",
                "The shipment and training crate were traced separately. "
                "The former stayed with the consignee at closing; the latter "
                "returned to the depot.",
            ))
        else:
            ending = rng.choice((
                "The consignee signed on arrival but subsequently returned "
                "the actual shipment. At closing it was at the depot; "
                "the later delivery signature concerned a training crate.",
                "A second delivery was proposed but never made. The actual "
                "shipment was back at the depot at closing.",
                "The shipment was collected from the consignee before closing. "
                "An earlier retained-goods report is withdrawn.",
                "The shipment and training crate were traced separately. "
                "The former returned to the depot before closing; the latter "
                "stayed with the consignee.",
            ))
        final_audit = (
            f"Signed final carrier audit for “{nickname}”. {ending} "
            "This audit supersedes the provisional custody message and "
            "settles the shipment's custody at the closing date."
        )
        paragraphs.append((8, final_audit))

        for section_index, paragraph in paragraphs:
            sections[section_index].append(paragraph)
            estimated_length += len(paragraph) + 2

        cases.append({
            "docket": docket,
            "nickname": nickname,
            "contract": contract_name,
            "final_radio": final_radio,
            "waiver_signed": waiver_signed,
            "moisture": moisture,
            "vibration": vibration,
            "seal": seal,
            "retained": retained,
            "units": final_units,
            "damaged": final_damage,
        })

    for paragraphs in sections:
        rng.shuffle(paragraphs)
    context = render()

    truth = {office: 0 for office in OFFICES}
    eligible_count = 0
    for case in cases:
        contract = contracts[case["contract"]]
        quality_ok = _quality(
            contract["gate"], case["moisture"], case["vibration"]
        )
        packaging_ok = case["seal"] or (
            case["waiver_signed"] and contract["waivers"]
        )
        eligible = case["retained"] and quality_ok and packaging_ok

        person = radio_to_person[case["final_radio"]]
        manager = final_managers[person]
        office = final_offices[manager]
        if eligible:
            eligible_count += 1
            credited_units = max(
                case["units"] - case["damaged"] - contract["allowance"], 0
            )
            truth[office] += credited_units * contract["rate"]

    question = (
        "Reconcile the entire May closing packet. What is the total earned "
        "credit for each of these offices: "
        + ", ".join(OFFICES)
        + "? Apply all signed corrections, the final custody findings, each "
        "agreement's quality and packaging rules, and the final contact-to-"
        "manager-to-office chain. Include offices with zero credits. Return "
        "one labeled integer total per office, preferably as a JSON object. "
        "Use numerals; do not include intermediate numeric calculations."
    )

    return {
        "context": context,
        "question": question,
        "answer": truth,
        "meta": {
            "task": "distributed_freight_closing",
            "version": 1,
            "author": "SHODAN",
            "author_model": "gpt-6-astra",
            "seed": seed,
            "size": size,
            "target_characters": TARGETS[size],
            "actual_characters": len(context),
            "shipments": len(cases),
            "eligible_shipments": eligible_count,
            "offices": len(OFFICES),
            "scoring": "Exact agreement on all labeled office totals.",
        },
    }


# Scoring concerns answer presentation only; it never parses the evidence.
# All numeric claims must be accounted for, including numbers after "or",
# negated alternatives, duplicate JSON keys, and subsequent corrections.
# A scalar alone cannot answer this seven-office mapping question.
_LABEL = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in OFFICES) + r")\b",
    re.IGNORECASE,
)
_CANONICAL = {name.casefold(): name for name in OFFICES}

# Capture malformed grouping, exponents, percentages, and abbreviated amounts
# as whole tokens so they cannot quietly become a different integer.
_NUMBER = re.compile(
    r"(?<![\w.])"
    r"[+-]?(?:\d+(?:,\d+)*(?:\.\d+)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?"
    r"(?:%|[kKmMbB](?!\w))?"
    r"(?!\w)"
)
_VALID_NUMBER = re.compile(
    r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?"
)
_WORDS = re.compile(r"[A-Za-z]+")
_CONNECTORS = frozenset("""
    a an all amount amounts accounting after agreement agreements allocated
    allocation allowance allowances amendments and answer applying are as at
    attributable attributed balance be belongs by closing corrected corrections
    credit credited credits custody damaged damage dollars earned earns eligible
    equals exactly final findings for from gives has have in integer is it its
    management may net of office offices only per receives reconciled
    reconciliation recorded relevant responsibility result results s shipment
    shipments signed stands sum summed the their therefore these this to total
    totaled totaling totals units usd value was were with yields
""".split())
_ALTERNATIVES = frozenset(("or", "versus", "vs", "either"))
_SCALE_SUFFIX = re.compile(
    r"\s*(?:%|/|(?:thousand|million|billion|trillion|percent|per\s+cent)\b)",
    re.IGNORECASE,
)


def _bridge_ok(fragment):
    """Recognize ordinary label/value linking language, not answer evidence."""
    words = _WORDS.findall(fragment.casefold())
    return all(word in _CONNECTORS for word in words)


def _full_matching(candidates, fixed=None):
    """Match every numeric occurrence to a distinct label occurrence.

    The graph is tiny for normal answers. This iterative augmenting-path
    implementation avoids recursion and does not consult ground-truth values.
    """
    chosen = {}
    owner = {}
    fixed_number = None
    if fixed is not None:
        fixed_number, fixed_label = fixed
        if fixed_label not in candidates[fixed_number]:
            return None
        chosen[fixed_number] = fixed_label
        owner[fixed_label] = fixed_number

    for start in range(len(candidates)):
        if start in chosen:
            continue
        queue = [start]
        seen_numbers = {start}
        parent = {}
        free_label = None
        cursor = 0

        while cursor < len(queue) and free_label is None:
            number = queue[cursor]
            cursor += 1
            for label in candidates[number]:
                if label in parent:
                    continue
                parent[label] = number
                if label not in owner:
                    free_label = label
                    break
                next_number = owner[label]
                if (
                    next_number != fixed_number
                    and next_number not in seen_numbers
                ):
                    seen_numbers.add(next_number)
                    queue.append(next_number)

        if free_label is None:
            return None

        label = free_label
        while label is not None:
            number = parent[label]
            previous_label = chosen.get(number)
            chosen[number] = label
            owner[label] = number
            label = previous_label

    return chosen


def score(answer_text: str, truth) -> float:
    """Exact mapping agreement, tolerant of ordinary answer presentation.

    Accepts JSON (including currency strings), Python dictionaries, markdown,
    tables, bullets, sentences, case changes, office suffixes, decimal zeros,
    thousands separators, and either order of labels and amounts.

    Extra explanatory prose is allowed. As the question requests, numeric
    content must consist of labeled totals, not intermediate calculations.
    Every numeric occurrence must have an unambiguous office association.
    Alternatives and contradictory repetitions cannot be hidden in prose.
    """
    if not isinstance(answer_text, str) or not isinstance(truth, dict):
        return 0.0
    if set(truth) != set(OFFICES):
        return 0.0
    if any(type(value) is not int for value in truth.values()):
        return 0.0

    text = (
        answer_text.replace("\u2212", "-")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("$", "")
    )
    labels = list(_LABEL.finditer(text))
    numbers = list(_NUMBER.finditer(text))
    if not labels or not numbers:
        return 0.0

    values = []
    for number in numbers:
        spelling = number.group()
        if _VALID_NUMBER.fullmatch(spelling) is None:
            return 0.0
        if _SCALE_SUFFIX.match(text[number.end():]):
            return 0.0
        try:
            value = Decimal(spelling.replace(",", ""))
        except InvalidOperation:
            return 0.0
        if not value.is_finite() or value != value.to_integral_value():
            return 0.0
        values.append(value)

    offices = [_CANONICAL[label.group().casefold()] for label in labels]

    # Adjacent events determine possible associations. In a normal dictionary
    # each number sits between two labels; matching resolves the direction
    # without using the expected amounts as a parsing oracle.
    events = []
    for index, label in enumerate(labels):
        events.append((label.start(), label.end(), "label", index))
    for index, number in enumerate(numbers):
        events.append((number.start(), number.end(), "number", index))
    events.sort()

    candidates = [[] for _ in numbers]
    for left, right in zip(events, events[1:]):
        gap = text[left[1]:right[0]]
        words = _WORDS.findall(gap.casefold())

        # Explicit choices between labels must not disappear just because
        # the next label happens to have a valid total.
        if (
            any(word in _ALTERNATIVES for word in words)
            and all(
                word in _CONNECTORS or word in _ALTERNATIVES
                for word in words
            )
        ):
            return 0.0

        if left[2] == right[2] or not _bridge_ok(gap):
            continue
        if left[2] == "number":
            candidates[left[3]].append(right[3])
        else:
            candidates[right[3]].append(left[3])

    if any(not options for options in candidates):
        return 0.0

    matched = _full_matching(candidates)
    if matched is None:
        return 0.0

    # Reject any alternative complete parsing that changes a number's office.
    # Equivalent references to the same office are harmless.
    for number, options in enumerate(candidates):
        office = offices[matched[number]]
        for label in options:
            if offices[label] != office:
                if _full_matching(candidates, (number, label)) is not None:
                    return 0.0

    observations = {office: [] for office in OFFICES}
    for number in range(len(numbers)):
        office = offices[matched[number]]
        observations[office].append(values[number])

    for office, expected in truth.items():
        observed = observations[office]
        if not observed or any(value != Decimal(expected) for value in observed):
            return 0.0
    return 1.0


def _self_test(truth):
    items = list(truth.items())
    reversed_items = list(reversed(items))
    plain = json.dumps(truth)
    labeled = "; ".join(
        f"{office} office: {amount}" for office, amount in items
    )

    correct_formats = [
        str(truth),                          # Bare mapping value.
        plain,
        plain + ".",
        "The answer is " + plain + ".",
        "**" + plain + "**",
        "*" + plain + "*",
        '"' + plain + '"',
        "