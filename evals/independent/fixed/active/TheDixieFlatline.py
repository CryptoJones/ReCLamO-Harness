import random
import re

def generate(seed: int, size: str) -> dict:
    rng = random.Random(seed)

    if size == "small":
        num_messages = 350
        num_signals = 20
    elif size == "medium":
        num_messages = 1700
        num_signals = 100
    elif size == "large":
        num_messages = 7000
        num_signals = 400
    else:
        raise ValueError("size must be small, medium, or large")

    # Entities
    names = [
        "Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Heidi", "Ivan", "Judy",
        "Mallory", "Niaj", "Oscar", "Peggy", "Rupert", "Sybil", "Trent", "Victor", "Walter", "Zoe",
        "Arthur", "Betty", "Carl", "Doris", "Earl", "Fay", "George", "Helen", "Ian", "Jane",
        "Karl", "Laura", "Manny", "Nora", "Orson", "Paula", "Quinn", "Rita", "Steve", "Tina",
        "Ulysses", "Vera", "Will", "Xena", "Yusuf", "Zara"
    ]
    roles = [
        "Head of IT", "Director of Security", "Chief Janitor", "VP of Operations",
        "Lead Auditor", "Compliance Officer", "Night Watchman", "Facilities Manager", "HR Lead"
    ]
    locations = [f"Room {i}" for i in range(101, 150)] + [
        "The Vault", "Datacenter Alpha", "Datacenter Beta", "Offsite Storage",
        "Basement Level 1", "Executive Suite", "The Annex", "Server Room C"
    ]

    rng.shuffle(names)
    rng.shuffle(locations)

    def get_new_alias():
        adjs = ["Red", "Blue", "Black", "Omega", "Alpha", "Ghost", "Null", "Void", "Iron", "Stone"]
        nouns = ["Protocol", "Drive", "Archive", "Payload", "Key", "Matrix", "Core", "Box", "File"]
        return f"The {rng.choice(adjs)} {rng.choice(nouns)} {rng.randint(10, 99)}"

    target_original_name = "The Genesis Drive"
    current_alias = target_original_name
    current_holder = rng.choice(names)

    # Initial state tracking
    person_to_loc = {n: locations[i % len(locations)] for i, n in enumerate(names)}
    rng.shuffle(locations)
    role_to_person = {r: names[i % len(names)] for i, r in enumerate(roles)}

    # Ensure signal messages are randomly distributed but remain chronologically sequential
    signal_indices = sorted(rng.sample(range(0, num_messages), num_signals))
    signal_set = set(signal_indices)

    messages = []
    timestamp = 1672531200 # Jan 1 2023

    # DEFECT FIX: Establish initial locations and roles explicitly in the context.
    setup_events = [("loc", n) for n in names] + [("role", r) for r in roles]
    rng.shuffle(setup_events)
    
    for i, (ev_type, val) in enumerate(setup_events):
        timestamp += rng.randint(300, 3600)
        msg_header = f"Message-ID: <setup_{i:04d}@corp.local>\nDate: {timestamp}"
        if ev_type == "loc":
            name = val
            loc = person_to_loc[name]
            template = rng.choice([
                "From: Facilities\nTo: {n}\nSubject: Welcome\n\nYour assigned office is {l}. Please pick up your keys.",
                "From: HR\nTo: {n}\nSubject: Directory update\n\nWe have you listed in {l}. Let us know if this is incorrect.",
                "From: IT\nTo: {n}\nSubject: Network hookup\n\nWe activated the ethernet port in your workspace at {l}."
            ])
            body = template.format(n=name, l=loc)
        else:
            role = val
            person = role_to_person[role]
            template = rng.choice([
                "From: Management\nTo: All\nSubject: Organization Chart\n\nPlease be advised that {p} is our {r}.",
                "From: HR\nTo: All\nSubject: Role Confirmation\n\nDirect all {r} inquiries to {p}.",
                "From: {p}\nTo: All\nSubject: Introduction\n\nHi everyone, I will be serving as your {r}."
            ])
            body = template.format(p=person, r=role)
        messages.append(f"{msg_header}\n{body}")

    fake_assets = ["Financial Records 2024", "The Blueprints", "Encrypted USB-C", "Old Laptops", "The Coffee Fund"]
    noise_templates = [
        "From: {n1}\nTo: {n2}\nSubject: Lunch\n\nAre we still meeting at {loc} for lunch?",
        "From: IT Dept\nTo: All\nSubject: Outage\n\nPlease note that the server in {loc} is down for maintenance.",
        "From: {n1}\nTo: {n2}\nSubject: Status report\n\nI have finished the audit for {role}. Everything looks fine.",
        "From: {n1}\nTo: {n2}\nSubject: Distractor Asset\n\nI left the {fake_asset} with {n3}.",
        "From: HR\nTo: All\nSubject: Policy update\n\nRemember to lock your doors, especially near {loc}.",
        "From: {n1}\nTo: {n3}\nSubject: Re: Move\n\nI heard {n2} is thinking of moving to {loc}, is that true?",
        "From: Facilities\nTo: All\nSubject: Cleaning\n\nWe will be deep cleaning {loc} this weekend. Please remove personal items."
    ]

    # WHY REGEX/KEYWORD SEARCH FAILS:
    # 1. The asset's name changes continuously. A search for the original name only finds early history.
    # 2. Handoffs often go to abstract job roles (e.g., "Director of Security") rather than names, 
    #    requiring a separate cross-reference lookup of who held that role at that specific timestamp.
    # 3. People change locations independently of receiving the asset. The final holder's location 
    #    might have been established thousands of messages prior to them actually receiving the asset.
    # 4. Adversarial traps: At the very end of the log, we inject distractor emails discussing the 
    #    asset moving to fake locations "tomorrow", which baits regex lookups targeting the final alias.

    time_step = (365 * 24 * 3600) // num_messages

    for i in range(num_messages):
        timestamp += rng.randint(time_step // 2, time_step * 2)
        msg_header = f"Message-ID: <{i:06d}@corp.local>\nDate: {timestamp}"

        if i in signal_set:
            action = rng.choices(
                ["rename", "assign_role", "move", "handoff_direct", "handoff_role", "correction", "failed_move"],
                weights=[10, 10, 20, 25, 15, 10, 10],
                k=1
            )[0]

            if action == "rename":
                new_alias = get_new_alias()
                while new_alias in (current_alias, target_original_name):
                    new_alias = get_new_alias()
                body = f"From: Director\nTo: All\nSubject: Codename Update\n\nEffective immediately, for operational security, '{current_alias}' will now be known as '{new_alias}'."
                current_alias = new_alias

            elif action == "assign_role":
                new_person = rng.choice(names)
                target_role = rng.choice(roles)
                body = f"From: HR\nTo: All\nSubject: Personnel Change\n\nPlease welcome {new_person}, who is taking over as the new {target_role} starting today."
                role_to_person[target_role] = new_person

            elif action == "move":
                person = rng.choice(names)
                new_loc = rng.choice(locations)
                body = f"From: Facilities\nTo: {person}\nSubject: Office Relocation\n\nYour request is approved. {person}, please move your things to {new_loc} by EOD."
                person_to_loc[person] = new_loc

            elif action == "failed_move":
                person = rng.choice(names)
                fake_loc = rng.choice([l for l in locations if l != person_to_loc[person]])
                body = f"From: {person}\nTo: Facilities\nSubject: Re: Office Relocation\n\nI am cancelling my move to {fake_loc}. I am staying in {person_to_loc[person]}."

            elif action == "handoff_direct":
                new_holder = rng.choice([n for n in names if n != current_holder])
                body = f"From: {current_holder}\nTo: {new_holder}\nSubject: Custody Transfer\n\nConfirming I have physically handed '{current_alias}' to you."
                current_holder = new_holder

            elif action == "handoff_role":
                target_role = rng.choice(roles)
                new_holder = role_to_person[target_role]
                if new_holder == current_holder:
                    new_holder = rng.choice([n for n in names if n != current_holder])
                    body = f"From: {current_holder}\nTo: {new_holder}\nSubject: Custody Transfer\n\nConfirming I have physically handed '{current_alias}' to you."
                else:
                    body = f"From: {current_holder}\nTo: {target_role}\nSubject: Custody Transfer\n\nI have left '{current_alias}' on the desk of the {target_role}."
                current_holder = new_holder

            elif action == "correction":
                fake_holder = rng.choice([n for n in names if n != current_holder])
                new_holder = rng.choice([n for n in names if n not in (current_holder, fake_holder)])
                msg1 = f"From: {current_holder}\nTo: {fake_holder}\nSubject: Handing over\n\nI gave '{current_alias}' to you just now."
                # DEFECT FIX: remove the stray literal 'a' that used to appear
                # between the message header and the body of the typo message.
                messages.append(f"{msg_header}\n{msg1}")
                # DEFECT FIX: the original `if action != "correction":` guard
                # silently dropped the correction message itself. Emit it here
                # so the user's stated custodian matches the truth.
                timestamp += 60
                msg_header_corr = f"Message-ID: <{i:06d}b@corp.local>\nDate: {timestamp}"
                body = f"From: {current_holder}\nTo: All\nSubject: CORRECTION: Handing over\n\nDisregard my previous message! Typo in the address book. I actually gave '{current_alias}' to {new_holder}."
                current_holder = new_holder
                messages.append(f"{msg_header_corr}\n{body}")
            else:
                messages.append(f"{msg_header}\n{body}")

        else:
            n1, n2, n3 = rng.sample(names, 3)
            loc = rng.choice(locations)
            role = rng.choice(roles)
            fake_asset = rng.choice(fake_assets)
            template = rng.choice(noise_templates)
            body = template.format(n1=n1, n2=n2, n3=n3, loc=loc, role=role, fake_asset=fake_asset)
            messages.append(f"{msg_header}\n{body}")

    # Adversarial traps at the end to defeat grep/distance-based solvers
    timestamp += 3600
    adv_loc_1 = rng.choice([l for l in locations if l != person_to_loc[current_holder]])
    msg_header = f"Message-ID: <999998@corp.local>\nDate: {timestamp}"
    body = f"From: Auditor\nTo: {current_holder}\nSubject: The asset\n\nI heard '{current_alias}' is going to be moved to {adv_loc_1} tomorrow. Keep it safe in your current office until then."
    messages.append(f"{msg_header}\n{body}")

    timestamp += 3600
    adv_loc_2 = rng.choice([l for l in locations if l not in (person_to_loc[current_holder], adv_loc_1)])
    msg_header = f"Message-ID: <999999@corp.local>\nDate: {timestamp}"
    body = f"From: IT\nTo: All\nSubject: Audit\n\nCan whoever has '{current_alias}' please bring it to {adv_loc_2} by next Friday for inspection?"
    messages.append(f"{msg_header}\n{body}")

    final_location = person_to_loc[current_holder]
    context = "\n\n".join(messages)
    question = f"What is the final physical location of the asset originally known as '{target_original_name}'? Extract ONLY the exact location name."

    return {
        "context": context,
        "question": question,
        "answer": final_location,
        "meta": {
            "final_holder": current_holder,
            "final_alias": current_alias,
            "num_messages": len(messages),
            "context_length": len(context)
        }
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

# --- round-4 lane helpers (this file only; same text in every round-4 scorer that uses them) ---
_R4_ALT_ANY = _re4.compile(
    r"\b(?:possibly|probably|maybe|perhaps|could\s+be|might\s+be|"
    r"can(?:no|')t\s+(?:be\s+)?determine[d]?|unclear|ambiguous|uncertain)\b",
    _re4.IGNORECASE,
)
_R4_ALT_LINK = _re4.compile(r"\b(?:or|either|alternatively)\b", _re4.IGNORECASE)


def _r4_hedged(segment: str, spans) -> bool:
    """Rule 3, read strictly: at least two DISTINCT candidates in the segment AND the
    alternative is offered between them ("X or Y", "either X or Y"), or the segment declares
    uncertainty outright ("possibly", "cannot be determined"). A bare "or" elsewhere in the
    segment ("unassigns or reassigns", "denied or withdrawn") is not a hedge.
    spans: iterable of (start, end, key) for candidate occurrences inside segment."""
    spans = list(spans)
    keys = {k for _, _, k in spans}
    if len(keys) < 2 or not _r4_explicit_alternative(segment):
        return False
    if _R4_ALT_ANY.search(segment):
        return True
    ordered = sorted(spans, key=lambda x: (x[0], x[1]))
    for (s1, e1, k1), (s2, e2, k2) in zip(ordered, ordered[1:]):
        if k1 != k2 and s2 - e1 <= 80 and _R4_ALT_LINK.search(segment[e1:s2]):
            return True
    return False


def _r4_lead(text: str) -> str:
    """Answer-first layout: a short standalone first line ("**Unassigned**", "**Room 130**",
    "**$4,311.31**") followed by the explanation. Returned only when the text has more than
    one paragraph, the first paragraph is a single line of at most 80 chars, and no answer
    marker ("Final answer", "Therefore", ...) opens a later line (that later line is then the
    final statement, not the lead); else ""."""
    t = text.strip()
    paras = [p for p in _re4.split(r"\n\s*\n", t) if p.strip()]
    if len(paras) < 2:
        return ""
    first = paras[0].strip()
    if "\n" in first or len(first) > 80:
        return ""
    last = None
    for m in _R4_MARKER.finditer(t):
        last = m
    if last is not None and last.start() >= len(first):
        return ""
    return first
# --- end round-4 lane helpers ---


_R4_LOCATION = _re4.compile(
    r"\b(?:server room c|room \d{3}|the vault|vault|datacenter alpha|datacenter beta|"
    r"offsite storage|basement level 1|executive suite|the annex|annex)\b"
)


def _r4_locations(text_low: str):
    """Occurrences of the generator's location names in lower-cased text; key drops 'the '."""
    out = []
    for m in _R4_LOCATION.finditer(text_low):
        k = m.group(0)
        if k.startswith("the "):
            k = k[4:]
        out.append((m.start(), m.end(), k))
    return out


def score(answer_text: str, truth: str) -> float:
    """Round-4 scorer for TheDixieFlatline: grades the FINAL STATEMENT.

    - 1.0 when the final location is named (case-insensitive, tolerant of formatting, prose,
      quotes; "The Annex" also as "Annex") and the final segment does not pick another one.
    - 0.3 when the final segment offers an explicit alternative between two locations
      ("either Room 118 or Room 130").
    - 0.0 when the truth is absent or the final statement names only other locations.
    "moved from X to Y" is not a hedge: the destination is the answer.
    """
    if not isinstance(answer_text, str) or not answer_text.strip():
        return 0.0
    norm = _r4_normalize(answer_text)
    ans_clean = re.sub(r"[^\w\s]", " ", norm.lower())
    ans_clean = re.sub(r"\s+", " ", ans_clean).strip()
    tru_clean = re.sub(r"[^\w\s]", " ", truth.lower())
    tru_clean = re.sub(r"\s+", " ", tru_clean).strip()
    pattern = r"\b" + re.escape(tru_clean) + r"\b"
    truth_found = re.search(pattern, ans_clean) is not None
    if not truth_found and tru_clean.startswith("the "):
        # Accept the no-article form: "The Annex" -> "Annex" matches.
        stripped = tru_clean[4:]
        if stripped and re.search(r"\b" + re.escape(stripped) + r"\b", ans_clean):
            truth_found = True
    if not truth_found:
        return 0.0
    tkey = tru_clean[4:] if tru_clean.startswith("the ") else tru_clean
    seg_low = _r4_segment(norm).lower()
    locs = _r4_locations(seg_low)
    if locs and tkey not in {k for _, _, k in locs}:
        lead = _r4_lead(norm).lower()
        lead_locs = _r4_locations(lead) if lead else []
        if lead_locs and tkey in {k for _, _, k in lead_locs}:
            seg_low, locs = lead, lead_locs
        else:
            return 0.0
    if locs:
        return 0.3 if _r4_hedged(seg_low, locs) else 1.0
    # The final segment names no location (e.g. "ROOM 118" survives lower-casing, so this is
    # rare): widen to the whole text.
    low = norm.lower()
    return 0.3 if _r4_hedged(low, _r4_locations(low)) else 1.0

if __name__ == "__main__":
    for sz in ["small", "medium", "large"]:
        data = generate(seed=0, size=sz)
        print(f"--- Size: {sz.upper()} ---")
        print(f"Context Length: {len(data['context'])} characters")
        print(f"Question: {data['question']}")
        print(f"Truth: {data['answer']}")
        print(f"Meta: {data['meta']}")
        print()

        truth = data['answer']
        # Verification assertions
        assert score(str(truth), truth) == 1.0
        assert score(f"I am pretty sure it is located in {truth}.", truth) == 1.0
        # Extra prose is still 1.0 — no giant-text penalty; the audit found that
        # penalty too aggressive (a single sentence of context around the answer
        # could trigger it).
        long = f"{truth} — and after a long series of renames and custodian changes documented in the thread, this is the final physical location of the asset."
        assert score(long, truth) == 1.0
        assert score("Totally Wrong Location", truth) == 0.0

    print("Running self-tests to verify final locations exist in context...")
    for sz in ["small", "medium", "large"]:
        for s in range(10):
            d = generate(seed=s, size=sz)
            assert d['answer'] in d['context'], f"Defect: Answer {d['answer']} missing from context (seed {s}, size {sz})"
    print("All self-tests passed.")

    # ----- Defect-specific regression: the CORRECTION message must be in context -----
    # Original bug: a `correction` action was guarded by `if action != "correction":`,
    # so the body of the correction email itself was never appended. A solver could
    # only see the (misleading) typo message. We now emit the correction explicitly;
    # IF a typo message fires for a given seed, the matching CORRECTION message
    # must also be reachable in the context.
    for sz in ["small", "medium", "large"]:
        for s in range(10):
            d = generate(seed=s, size=sz)
            ctx = d['context']
            # The stray 'a' that used to appear at the end of the Date header
            # for typo messages must be gone.
            assert not re.search(r"Date: \d+a\n", ctx), (
                f"Defect: stray 'a' found after Date header "
                f"(seed={s}, size={sz})"
            )
            # If a typo "Handing over" message fires for this seed, the matching
            # CORRECTION: Handing over must also be present.
            typo_count = ctx.count("Subject: Handing over\n")
            corr_count = ctx.count("Subject: CORRECTION: Handing over\n")
            assert typo_count == corr_count, (
                f"Defect: typo count ({typo_count}) != correction count ({corr_count}) "
                f"for seed={s}, size={sz} (correction email not being emitted)"
            )
    print("DixieFlatline: defect-specific assertions PASS (correction message emitted; no stray 'a').")

    # ----- Scorer regression: every format the audit probes must score 1.0 -----
    for seed in range(5):
        d = generate(seed, "small")
        truth = d["answer"]
        positives = {
            "as_is": truth,
            "sentence": f"The answer is {truth}.",
            "bold": f"**{truth}**",
            "italic": f"*{truth}*",
            "bold_in_sentence": f"The location is **{truth}**.",
            "bullet": f"- {truth}",
            "json": __import__("json").dumps({"location": truth}),
            "lead_in_explanation": f"After applying every amendment and reversal, the location is {truth}.",
            "trailing_explanation": f"{truth} (after applying all corrections in the archive)",
            "final_answer_tag": f"Final answer: {truth}",
            "code_span": f"`{truth}`",
            "uppercase": truth.upper(),
            "lowercase": truth.lower(),
            "newline_after": f"{truth}\n",
            "quoted": f'"{truth}"',
            "long_sentence": f"The final physical location of the asset originally known as 'The Genesis Drive' is {truth}.",
            "medium_sentence": f"The asset's final physical location is {truth}.",
        }
        if truth.startswith("The "):
            positives["no_article"] = truth[4:]
        for k, s in positives.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, (
                f"DixieFlatline positive {k!r} should score 1.0 (seed={seed}); got {sc}"
            )
    print("DixieFlatline: scorer regression battery PASS (formats in).")

    # ----- Round 4 (issue #95): final-statement scoring -----
    # A custody/location history ("moved from X to Y"), a timeline table, a \boxed{} answer
    # and an answer-first layout all score 1.0 when the final location is right; the
    # destination of a move is the answer, not a hedge. A final statement naming a different
    # location is 0.0 even when the truth appears in the working; "either A or B" is 0.3.
    for seed in range(5):
        d = generate(seed, "small")
        t = d["answer"]
        o = "Room 101" if t != "Room 101" else "Room 102"
        o2 = "The Vault" if t != "The Vault" else "The Annex"
        r4_pos = {
            "history_then_final": (f"The asset was first in {o}, moved to {o2} with the Head of IT, and after the "
                                   f"CORRECTION email it ended up in {t}.\n\nFinal answer: {t}"),
            "moved_from_to": f"It moved from {o} to {t}",
            "table_then_final": (f"| Step | Holder | Location |\n|---|---|---|\n| 1 | Alice | {o} |\n| 2 | Bob | {o2} |\n"
                                 f"| 3 | Carl | {t} |\n\n**Final location: {t}**"),
            "boxed": f"\\boxed{{\\text{{{t}}}}}",
            "answer_first_then_explanation": (f"**{t}**\n\nThe auditor's note about moving it to {o} tomorrow is a future "
                                              f"event, so the current office of the final holder stands."),
            "trap_dismissed_in_final": (f"Final answer: {t} (the request to bring it to {o2} by Friday has not happened yet)"),
            "cancelled_move_in_working": (f"Rupert cancelled his move to {o} and stayed in {t}; the drive was handed to "
                                          f"him last.\n\n**{t}**"),
        }
        for k, s in r4_pos.items():
            sc = score(s, t)
            assert sc == 1.0, f"DixieFlatline round-4 positive {k!r} should score 1.0 (seed={seed}, truth={t!r}); got {sc}"
        r4_neg = {
            "either_in_final": (f"Final answer: either {o} or {t}", 0.3),
            "possibly_in_final": (f"Final answer: {t}, or possibly {o2}", 0.3),
            "wrong_final_truth_in_working": (f"The holder's office was {t} at one point.\n\nFinal answer: {o}", 0.0),
            "wrong_table_final": (f"| 1 | Alice | {t} |\n| 2 | Bob | {o} |\n\n**Final location: {o}**", 0.0),
        }
        for k, (s, want) in r4_neg.items():
            sc = score(s, t)
            assert sc == want, f"DixieFlatline round-4 negative {k!r} should score {want} (seed={seed}, truth={t!r}); got {sc}"
    print("DixieFlatline: round-4 final-statement assertions PASS (moves are not hedges; wrong finals stay wrong).")
