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

    # Radio names are deliberately permuted independently of personal names.
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

    # Nicknames and docket numbers have no relationship to eligibility.
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

        # Former/latter resolution is needed to associate final test outcomes.
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

    # Different desks file their records independently. Corrections remain
    # later than the records they supersede because section order is fixed.
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


# Round 4 (2026-10-19, issue #95): final-statement scoring; see evals/TEST-PLAN.md section 1d.
# --- round-4 shared helpers (pasted verbatim into every round-4 scorer; keep in sync) ---
# Round 4 (2026-10-19, issue #95): a scorer reads the answer's FINAL STATEMENT, not its working.
# Formatting is normalised first (LaTeX money, \boxed{}, markdown emphasis, tables), then the
# final segment is located, and "hedge" means an explicit alternative offered inside that
# segment ("X or Y", "either X or Y", "possibly X"), never the mere presence of other numbers
# or names earlier in a shown calculation. Both arms are scored by the same code.
import re as _re4

_R4_MARKER = _re4.compile(
    r"(?im)^[\s#>*_|\-]*(?:final\s+answer|final\s+result|final\s+total|answer|conclusion|"
    r"result|in\s+summary|summary|therefore|so,?\s+the|thus,?\s+the|hence|total)\b"
)
_R4_ALT = _re4.compile(
    r"\b(?:either|alternatively|possibly|probably|maybe|perhaps|could\s+be|might\s+be|"
    r"can(?:no|')t\s+(?:be\s+)?determine[d]?|unclear|ambiguous|uncertain)\b|"
    r"\b(?:or)\b",
    _re4.IGNORECASE,
)


def _r4_normalize(text: str) -> str:
    """Flatten LaTeX / markdown money and emphasis so one regex sees one surface form."""
    t = text.replace("\u2212", "-").replace("\u00a0", " ")
    t = t.replace("{,}", ",").replace("\\$", "$").replace("\\,", "").replace("\\!", "")
    for _ in range(3):  # nested \boxed{\text{...}} etc.
        t = _re4.sub(r"\\(?:boxed|text|textbf|mathrm|mathbf|underline)\{([^{}]*)\}", r"\1", t)
    t = t.replace("$$", " ")
    t = _re4.sub(r"\\\(|\\\)|\\\[|\\\]", " ", t)
    t = _re4.sub(r"(\*\*|__)(.+?)\1", r"\2", t, flags=_re4.DOTALL)
    t = _re4.sub(r"`+", "", t)
    t = _re4.sub(r"^\s*\|?[\s:\-|]+\|?\s*$", "", t, flags=_re4.MULTILINE)  # table rules
    t = t.replace("|", " ")
    return t


def _r4_segment(text: str) -> str:
    """The final statement: from the last answer marker to the end, else the last paragraph.

    A marker is a line that opens with "final answer", "answer", "conclusion", "total",
    "therefore" and the like. If no marker exists the last non-empty paragraph is used.
    Callers widen to the whole text when the segment holds no candidate of the kind they
    need (for example a name when the total line carries only the amount).
    """
    t = text.rstrip()
    if not t:
        return ""
    last = None
    for m in _R4_MARKER.finditer(t):
        last = m
    if last is not None:
        return t[last.start():]
    paras = [p for p in _re4.split(r"\n\s*\n", t) if p.strip()]
    return paras[-1] if paras else t


def _r4_explicit_alternative(segment: str) -> bool:
    """True when the final statement itself offers alternatives or declares uncertainty."""
    return bool(_R4_ALT.search(segment))
# --- end round-4 shared helpers ---


# Scoring parses answer formatting, not benchmark evidence. All seven numeric
# totals must agree exactly. No partial credit or numeric tolerance is used.
_NUMBER = re.compile(
    r"(?<![\w.+-])"
    r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?![\w]|\.\d)"
)
_CONNECTORS = {
    "a", "an", "and", "at", "balance", "closing", "credit", "credits",
    "earned", "earns", "equals", "final", "for", "has", "is", "net",
    "of", "office", "receives", "stands", "the", "to", "total", "totals",
    "units",
}
# Round 4: words that turn a second clean number in the same label window into an
# explicit alternative ("Alderwick: 5 or 7", "Alderwick: possibly 5, maybe 7").
_ALT_WORDS = {"or", "either", "possibly", "probably", "maybe", "perhaps", "alternatively"}
# Round 4: an answer that stops mid-sentence (output cap) has no final statement. The
# last line must end with a terminator/closer, a number, or a unit word.
_R4_CLOSERS = ".!?:;)]}\"'\u201d\u2019*|%$"
_R4_END_WORDS = {"credits", "credit", "units", "none", "zero", "nil"}


def _r4_concluded(text: str) -> bool:
    t = text.rstrip()
    if not t:
        return False
    if t[-1] in _R4_CLOSERS or t[-1].isdigit():
        return True
    m = re.search(r"([A-Za-z][A-Za-z'\u2019-]*)\s*$", t)
    return bool(m) and m.group(1).lower() in _R4_END_WORDS


def _label_observation(text: str, start: int, end: int):
    """Clean numbers in a label window, as (value, hedged).

    A clean number has nothing but connector words (and, for the hedge test, alternative
    words) between the label and itself, no unit/percent suffix. Returns None when the
    window holds no clean number. Hedged = an alternative word in the window together with
    two distinct clean numbers.
    """
    segment = text[start:end]
    values = []
    saw_alt = False
    for number in _NUMBER.finditer(segment):
        prefix = segment[:number.start()]
        words = re.findall(r"[A-Za-z]+", prefix.casefold())
        alts = [w for w in words if w in _ALT_WORDS]
        if any(word not in _CONNECTORS and word not in _ALT_WORDS for word in words):
            continue
        # digits/operators before the number: allowed only when they belong to an earlier
        # clean number of this window (the hedge case), never arithmetic.
        prior_numeric = re.sub(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", "", prefix)
        if values and re.search(r"[+\-*/=]", prior_numeric):
            continue
        if not values and re.search(r"[\d+-]", prefix):
            continue
        suffix = segment[number.end():]
        if re.match(r"\s*(?:%|/|[eE][+-]?\d|[kKmMbB]\b)", suffix):
            continue
        try:
            value = Decimal(number.group().replace(",", ""))
        except InvalidOperation:
            continue
        if values and not alts:
            break  # a second number without an alternative word is trailing prose
        values.append(value)
        saw_alt = saw_alt or bool(alts)
    if not values:
        return None
    hedged = saw_alt and len(set(values)) >= 2
    return values[0], hedged


def score(answer_text: str, truth) -> float:
    """Accept JSON, Python dict notation, tables, lists, or labeled prose.

    Office order, letter case, ordinary punctuation, thousands commas, and
    surrounding prose do not matter. Missing offices and incorrect values
    fail. Hedges ("Alderwick: 5 or 7") in the authoritative label window
    fail.

    Round 4 (issue #95): the text is formatting-normalised; for each office
    the authoritative observation is the one inside the final segment when
    the segment carries that office's label, else the LAST clean observation.
    Working that mentions an office with a different figure before the final
    statement is no longer penalised. An answer that stops mid-sentence has
    no final statement and scores 0.0.
    """
    if not isinstance(answer_text, str) or not isinstance(truth, dict):
        return 0.0
    if set(truth) != set(OFFICES):
        return 0.0
    if any(type(value) is not int for value in truth.values()):
        return 0.0

    text = _r4_normalize(answer_text)
    if not _r4_concluded(text):
        return 0.0
    segment = _r4_segment(text)
    seg_start = text.rstrip().rfind(segment) if segment else len(text)
    label_pattern = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in OFFICES) + r")\b",
        re.IGNORECASE,
    )
    labels = list(label_pattern.finditer(text))
    canonical = {name.casefold(): name for name in OFFICES}
    observations = {name: [] for name in OFFICES}  # (position, value, hedged)

    for index, label in enumerate(labels):
        # Only numbers within a tight proximity to the label (60 chars, cut at
        # the next label) can be its value; a wider window (180) is tried when
        # the layout puts the number farther on.
        next_start = labels[index + 1].start() if index + 1 < len(labels) else len(text)
        obs = _label_observation(text, label.end(), min(next_start, label.end() + 60))
        if obs is None:
            obs = _label_observation(text, label.end(), min(next_start, label.end() + 180))
        if obs is None:
            continue
        office = canonical[label.group().casefold()]
        observations[office].append((label.start(), obs[0], obs[1]))

    for office, expected in truth.items():
        values = observations[office]
        if not values:
            return 0.0
        in_segment = [v for v in values if v[0] >= seg_start]
        _, value, hedged = (in_segment or values)[-1]
        if hedged or value != Decimal(expected):
            return 0.0
    return 1.0


if __name__ == "__main__":
    for requested_size in ("small", "medium", "large"):
        result = generate(0, requested_size)
        truth = result["answer"]
        print(
            f"{requested_size}: {len(result['context']):,} characters; "
            f"{len(result['context'].split()):,} whitespace-delimited words; "
            f"{result['meta']['shipments']} shipments"
        )
        print("Question:", result["question"])
        print("Truth:", json.dumps(truth, sort_keys=True))

        assert score(str(truth), truth) == 1.0
        assert score(json.dumps(truth), truth) == 1.0
        formatted = "Reconciled results:\n" + "\n".join(
            f"- {office.upper()} has {amount:,} credits."
            for office, amount in reversed(list(truth.items()))
        ) + "\nReconciliation complete."
        assert score(formatted, truth) == 1.0

        changed = {office: amount + 1 for office, amount in truth.items()}
        missing = dict(truth)
        missing.pop(OFFICES[0])
        assert score(str(changed), truth) < 1.0
        assert score(str(missing), truth) < 1.0
        assert score("All offices earned the same amount.", truth) < 1.0
        contradictory = (
            str(truth) + f"\n{OFFICES[0]}: {truth[OFFICES[0]] + 1}"
        )
        assert score(contradictory, truth) < 1.0
        print()

    # Scorer regression for the formats the audit flagged.
    for seed in range(5):
        d = generate(seed, "small")
        truth = d["answer"]
        offs = list(truth)
        positives = {
            "json": json.dumps(truth),
            "json_pretty": json.dumps(truth, indent=2),
            "py_dict": str(truth),
            "colon_lines": "\n".join(o + ": " + str(truth[o]) for o in offs),
            "bullets_bold": "\n".join("- **" + o + "**: " + str(truth[o]) for o in offs),
            "md_table": "| Office | Credits |\n|---|---|\n" + "\n".join("| " + o + " | " + str(truth[o]) + " |" for o in offs),
            "credits_suffix": "\n".join(o + ": " + str(truth[o]) + " credits" for o in offs),
            "office_word": "\n".join(o + " office: " + str(truth[o]) for o in offs),
            "Office_label_json": json.dumps({o + " Office": truth[o] for o in offs}),
            "prose_earned": "; ".join(o + " earned " + str(truth[o]) for o in offs) + ".",
            "intro_list": ("Totals for Alderwick, Brindleford, Cairnstead, Dunmere, Elmbridge, Fenhurst and Gorsehaven:\n"
                           + "\n".join(o + ": " + str(truth[o]) for o in offs)),
            "fenced_json": "```json\n" + json.dumps(truth, indent=2) + "\n```",
            "equals": ", ".join(o + " = " + str(truth[o]) for o in offs),
            "with_note_after": json.dumps(truth) + "\nNote: offices with no qualifying shipments are 0.",
            "em_dash": "\n".join(o + " — " + str(truth[o]) for o in offs),
            "zero_word_none": "\n".join(o + ": " + (str(truth[o]) if truth[o] else "0 (none)") for o in offs),
            "paren_unit": "\n".join(o + ": " + str(truth[o]) + " (credits)" for o in offs),
        }
        for k, s in positives.items():
            sc = score(s, truth)
            assert sc == 1.0, f"SHODAN positive {k!r} should score 1.0 (seed={seed}); got {sc}"
        # Hedge detection: two different numbers after a label -> 0.0
        if truth[offs[0]] != truth[offs[1]]:
            h = offs[0] + ": " + str(truth[offs[0]]) + " or " + str(truth[offs[1]]) + "\n" + offs[1] + ": " + str(truth[offs[1]])
            assert score(h, truth) < 1.0
        # Negation: "Alderwick: not 5" -> 0.0
        neg = offs[0] + ": not " + str(truth[offs[0]]) + "\n" + offs[1] + ": " + str(truth[offs[1]])
        assert score(neg, truth) < 1.0
        # Off by one
        w = dict(truth); w[offs[0]] = truth[offs[0]] + 1
        assert score(json.dumps(w), truth) < 1.0
        # Missing office
        m = dict(truth); m.pop(offs[-1])
        assert score(json.dumps(m), truth) < 1.0

        # Round 4 (issue #95): the final statement is graded; working before it is not.
        o0, o1 = offs[0], offs[1]
        r4_positives = {
            # markdown table of per-shipment lines ending in the per-office total rows
            "table_lines_then_totals": (
                "| Office | Shipment | Credits |\n|---|---|---|\n| " + o0 + " | S-101 | " + str(truth[o0] + 7) + " |\n"
                "| " + o0 + " | S-102 | " + str(truth[o0] + 9) + " |\n\n"
                "**Totals**\n\n| Office | Credits |\n|---|---|\n" + "\n".join("| " + o + " | " + str(truth[o]) + " |" for o in offs)
            ),
            # a LaTeX sum for one office followed by the full answer
            "latex_sum_then_answer": (
                "$$" + str(truth[o0] + 4) + " + " + str(max(truth[o0] - 4, 0)) + "$$ **= " + str(truth[o0] * 2) + "** before the waiver correction.\n\n"
                "Final answer:\n" + "\n".join(o + ": " + str(truth[o]) for o in offs)
            ),
            # history paragraph ("was X, then Y") followed by the final answer
            "history_then_final": (
                o0 + " was provisionally " + str(truth[o0] + 12) + ", then " + str(truth[o0] + 3) + " after the seal ruling, and "
                + o1 + " moved from " + str(truth[o1] + 5) + " to its closing figure.\n\n"
                "Final answer: " + json.dumps(truth)
            ),
            # boxed answer
            "boxed": "Working above.\n\n$\\boxed{\\text{" + ", ".join(o + ": " + str(truth[o]) for o in offs) + "}}$",
            # a working mention of an office with a different figure, then a JSON answer
            "working_mention_then_json": (
                "Working: " + ", ".join(o + " " + str(truth[o] + 10) for o in offs) + "\n\nFinal answer:\n" + json.dumps(truth)
            ),
            # answer first, then a note naming an office with another figure
            "final_then_note": json.dumps(truth) + "\n\nNote: " + o0 + " would have been " + str(truth[o0] + 5) + " without the waiver.",
            # an office mentioned in prose with a non-connector prefix before the answer
            "prose_mention_then_answer": (
                "The " + o0 + " contact Hector Lane reports to Dorian Ellis for 3 shipments.\n\n" + json.dumps(truth)
            ),
        }
        for k, s_ in r4_positives.items():
            sc = score(s_, truth)
            assert sc == 1.0, f"SHODAN round-4 positive {k!r} should score 1.0 (seed={seed}); got {sc}"
        r4_negatives = {
            # the final segment hedges one office
            "final_either_or": "\n".join(o + ": " + str(truth[o]) for o in offs[1:]) + "\n" + o0 + ": either " + str(truth[o0]) + " or " + str(truth[o0] + 3),
            "final_or": o0 + ": " + str(truth[o0]) + " or " + str(truth[o0] + 3) + "\n" + "\n".join(o + ": " + str(truth[o]) for o in offs[1:]),
            # the final segment names the wrong figure while the working had the right one
            "final_wrong_working_right": (
                "Working: " + json.dumps(truth) + "\n\nFinal answer:\n" + json.dumps({**truth, o0: truth[o0] + 1})
            ),
            # cut off mid-sentence (output cap): no final statement
            "truncated": "Mapping radio names to persons:\n- \"Maple Crown\" -> Hector Lane\n- \"Evening Fox\" -> Greta Moss\n- \"Fr",
        }
        for k, s_ in r4_negatives.items():
            sc = score(s_, truth)
            assert sc < 1.0, f"SHODAN round-4 negative {k!r} should score < 1.0 (seed={seed}); got {sc}"
    print("SHODAN: scorer regression battery PASS (round-4 final-statement cases included).")
