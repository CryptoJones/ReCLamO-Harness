import random
import re
import string
from typing import Dict, Any, Tuple, List

# Predefined pools for natural-sounding generation
FIRST_NAMES = ["Alex", "Blake", "Casey", "Dana", "Elliot", "Finley", "Gray", "Harper", "Avery", "Quinn", "Riley", "Taylor", "Jordan", "Morgan", "Jamie", "Peyton", "Reese", "Skyler", "Frankie", "Leslie"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
DEPTS = ["Product", "Engineering", "Design", "Data Science", "Marketing", "Legal", "AI Ethics", "Compliance", "Research", "Operations"]
PROJECTS = ["Nexus", "Atlas", "Orion", "Phoenix", "Helios", "Apex", "Vertex", "Summit", "Catalyst", "Pinnacle"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
YEARS = [2023, 2024, 2025, 2026]

def _rand_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"

def _rand_dept(rng: random.Random) -> str:
    return rng.choice(DEPTS)

def _rand_project(rng: random.Random) -> str:
    return rng.choice(PROJECTS)

def _rand_date(rng: random.Random, start_year: int = 2023, end_year: int = 2026) -> str:
    year = rng.randint(start_year, end_year)
    month = rng.choice(MONTHS)
    day = rng.randint(1, 28)
    return f"{month} {day}, {year}"

def _format_para(text: str) -> str:
    return text.strip() + "\n\n"

def generate(seed: int, size: str) -> Dict[str, Any]:
    rng = random.Random(seed)
    
    # Size to approximate character targets
    size_map = {"small": 60000, "medium": 300000, "large": 1200000}
    target_chars = size_map[size]
    
    # We'll build a sequence of email entries
    emails = []
    # State tracking for ground truth
    ai_ethics_owner = None
    ai_ethics_dept = None
    
    # Initial setup email
    initiator = _rand_name(rng)
    dept = _rand_dept(rng)
    project = _rand_project(rng)
    date = _rand_date(rng, 2023, 2023)
    emails.append(
        f"From: {initiator} <{initiator.lower().replace(' ', '.')}@company.com>\n"
        f"To: {dept} Team <{dept.lower()}@company.com>\n"
        f"Date: {date}\n"
        f"Subject: Kickoff: {project} AI Ethics Review\n\n"
        f"Hi team,\n\n"
        f"We're starting the AI Ethics Review for Project {project}. "
        f"This will be led by the {dept} department initially. "
        f"Please hold for further assignments.\n"
    )
    # Initially unassigned; will be assigned in follow-ups
    
    # Generate a series of updates, corrections, and redistributions
    # We'll aim for about 20-30 core events that affect ownership, plus filler
    num_core_events = 25 if size == "small" else 40 if size == "medium" else 60
    # We'll generate core events that may change AI Ethics ownership
    # and many filler emails about other topics
    
    # Track all people mentioned to avoid too many unique names
    people = {initiator}
    # Add some more people for variety
    for _ in range(15):
        people.add(_rand_name(rng))
    people = sorted(list(people))  # Sort for deterministic iteration
    
    # We'll generate a timeline of events from 2023 to 2026
    timeline = []
    # Start with the kickoff
    timeline.append(("2023-01-15", "kickoff", None, dept))  # (date, type, owner, dept)
    
    # Generate events that change ownership
    current_owner = None
    current_dept = dept
    
    for i in range(num_core_events):
        # Progressively advance date
        year = 2023 + (i * 2 // 12)  # Slowly advance years
        month = (i * 2) % 12 + 1
        if month > 12:
            month -= 12
            year += 1
        day = rng.randint(1, 28)
        date_str = f"{year}-{month:02d}-{day:02d}"
        readable_date = _rand_date(rng, year, year)  # Approximate
        
        event_type = rng.choice([
            "assign", "reassign", "decline", "cancel", "correct", "delegate", "note"
        ])
        
        if event_type == "assign" and current_owner is None:
            # Choose new owner from people, excluding initiator
            available_people = [p for p in people if p != initiator]
            new_owner = rng.choice(available_people)
            new_dept = _rand_dept(rng)
            timeline.append((date_str, "assign", new_owner, new_dept))
            current_owner = new_owner
            current_dept = new_dept
        elif event_type == "reassign" and current_owner is not None:
            # Sometimes reassign to same person but different dept (role change)
            if rng.random() < 0.3:
                new_dept = _rand_dept(rng)
                # Ensure dept change
                attempts = 0
                while new_dept == current_dept and attempts < 10:
                    new_dept = _rand_dept(rng)
                    attempts += 1
                if new_dept != current_dept:  # Only add if changed
                    timeline.append((date_str, "reassign", current_owner, new_dept))
                    current_dept = new_dept
            else:
                new_owner = rng.choice([p for p in people if p != current_owner])
                new_dept = _rand_dept(rng)
                timeline.append((date_str, "reassign", new_owner, new_dept))
                current_owner = new_owner
                current_dept = new_dept
        elif event_type == "decline" and current_owner is not None:
            timeline.append((date_str, "decline", current_owner, current_dept))
            current_owner = None  # Now unassigned
        elif event_type == "cancel" and current_owner is not None:
            timeline.append((date_str, "cancel", None, None))
            current_owner = None
            current_dept = None
        elif event_type == "correct" and current_owner is not None:
            # A correction that reaffirms or slightly adjusts
            if rng.random() < 0.5:
                # Just a reaffirmation
                timeline.append((date_str, "correct", current_owner, current_dept))
            else:
                # Correction to dept only
                new_dept = _rand_dept(rng)
                attempts = 0
                while new_dept == current_dept and attempts < 10:
                    new_dept = _rand_dept(rng)
                    attempts += 1
                if new_dept != current_dept:  # Only add if changed
                    timeline.append((date_str, "correct", current_owner, new_dept))
                    current_dept = new_dept
        # For delegate and note, we might not change ownership but generate email
        # We'll handle email generation separately
        
        # Also occasionally reset to unassigned then reassign later
        if rng.random() < 0.1 and current_owner is not None:
            timeline.append((date_str, "unassign", None, None))
            current_owner = None
            current_dept = None
    
    # Now generate actual email text for each timeline event, plus filler
    all_entries = []
    
    # Add the kickoff email as first entry (date fixed to match timeline[0][0]).
    _ky, _km, _kd = timeline[0][0].split("-")
    all_entries.append((
        timeline[0][0],  # date
        f"From: {initiator} <{initiator.lower().replace(' ', '.')}@company.com>\n"
        f"To: {dept} Team <{dept.lower()}@company.com>\n"
        f"Date: {MONTHS[int(_km) - 1]} {int(_kd)}, {_ky}\n"
        f"Subject: Kickoff: {project} AI Ethics Review\n\n"
        f"Hi team,\n\n"
        f"We're starting the AI Ethics Review for Project {project}. "
        f"This will be led by the {dept} department initially. "
        f"Please hold for further assignments.\n"
    ))
    
    # Process timeline events from index 1 onward
    for i in range(1, len(timeline)):
        date_str, etype, owner, dept_val = timeline[i]
        # Pick random people for from/to
        sender = rng.choice(people)
        # Recipient: sometimes team, sometimes individual
        if rng.random() < 0.4:
            recipient = f"{rng.choice(DEPTS).lower()} Team"
        else:
            recipient = rng.choice([p for p in people if p != sender])
        
        # Generate subject and body based on event type
        if etype == "assign":
            subject = f"Update: AI Ethics Review Lead Assigned"
            proj = rng.choice(PROJECTS)  # For variety in email
            body = (
                f"Hi {recipient.split()[0] if 'Team' not in recipient else 'team'},\n\n"
                f"I'm assigning the AI Ethics Review for Project {proj} to "
                f"{owner} from {dept_val}. Please direct all related questions to them.\n"
                f"Thanks,\n{sender}"
            )
        elif etype == "reassign":
            if owner is not None and (i == 1 or timeline[i-1][2] is not None):  # Person change
                subject = f"Update: AI Ethics Review Lead Changed"
                body = (
                    f"Hi team,\n\n"
                    f"Effective immediately, {owner} from {dept_val} will be taking over "
                    f"the AI Ethics Review responsibilities. "
                    f"The previous lead will no longer be involved.\n"
                    f"Please update your records.\n"
                    f"Thanks,\n{sender}"
                )
            else:  # Dept change only
                subject = f"Update: AI Ethics Review Department Change"
                body = (
                    f"Hi team,\n\n"
                    f"The AI Ethics Review will now be handled by the {dept_val} department, "
                    f"while {owner} remains the lead. "
                    f"This is to better align with compliance requirements.\n"
                    f"Thanks,\n{sender}"
                )
        elif etype == "decline":
            # Note: the truth computation treats "decline" as an ownership-changing event
            # that sets current_owner = None. The original email text said "Please reassign
            # this responsibility" but never said the position is now empty, so a careful
            # reader tracking only the most recent email could easily leave the original
            # lead in mind. Make it explicit so the email matches the truth.
            subject = f"Update: AI Ethics Review Lead Declined -- Position Now Unassigned"
            body = (
                f"Hi team,\n\n"
                f"I'm writing to confirm that the previous AI Ethics Review lead has declined "
                f"the role due to bandwidth constraints. Effective immediately, the AI Ethics "
                f"Review lead position is unassigned until a new lead can be confirmed. "
                f"Please update your records and re-circulate the call for a new lead.\n"
                f"Thanks,\n{sender}"
            )
        elif etype == "cancel":
            # Same as above: the truth is "Unassigned" after a cancel event; spell it out
            # in the body so the thread stays consistent with the key.
            subject = f"Update: AI Ethics Review Cancelled -- Position Now Unassigned"
            body = (
                f"Hi team,\n\n"
                f"The AI Ethics Review for Project {rng.choice(PROJECTS)} has been cancelled "
                f"and the lead position is now unassigned. No further action is required from "
                f"the previous reviewers and ownership will need to be re-confirmed before any "
                f"follow-up work begins.\n"
                f"Thanks,\n{sender}"
            )
        elif etype == "unassign":
            # Originally this fell through to the generic "Note: AI Ethics Review Update"
            # else-branch and produced an email that said "the AI Ethics Review is
            # progressing well. The team is handling the current deliverables.", which was
            # inconsistent with the truth key (which was now "Unassigned" because the
            # timeline's unassign event clears current_owner = None). The latest AI Ethics
            # email in the thread would then quietly disagree with the key. Add an explicit
            # branch that surfaces the unassigned state in the same prose style.
            subject = f"Update: AI Ethics Review Lead Unassigned"
            body = (
                f"Hi team,\n\n"
                f"This is to confirm that the AI Ethics Review lead position is now "
                f"unassigned. We are looking for a new lead to take over ownership and "
                f"will circulate a call for nominations shortly.\n"
                f"Thanks,\n{sender}"
            )
        elif etype == "correct":
            if rng.random() < 0.5:  # Reaffirmation
                subject = f"Confirmation: AI Ethics Review Ownership"
                body = (
                    f"Hi team,\n\n"
                    f"This is to confirm that {owner} from {dept_val} remains the lead "
                    f"for the AI Ethics Review. No changes have been made.\n"
                    f"Thanks,\n{sender}"
                )
            else:  # Dept correction
                subject = f"Correction: AI Ethics Review Department"
                body = (
                    f"Hi team,\n\n"
                    f"Please note a correction: the AI Ethics Review is under the {dept_val} department, "
                    f"not the previously mentioned one. {owner} remains the lead.\n"
                    f"Thanks,\n{sender}"
                )
        elif etype == "delegate":
            subject = f"Delegation: AI Ethics Review Task"
            body = (
                f"Hi {recipient.split()[0] if 'Team' not in recipient else 'team'},\n\n"
                f"I'm delegating the AI Ethics Review coordination to {owner} from {dept_val} "
                f"for the next phase. They will handle scheduling and documentation.\n"
                f"Thanks,\n{sender}"
            )
        else:  # note
            subject = f"Note: AI Ethics Review Update"
            body = (
                f"Hi team,\n\n"
                f"Quick note: the AI Ethics Review is progressing well. "
                f"{owner if owner else 'The team'} is handling the current deliverables.\n"
                f"Thanks,\n{sender}"
            )
        
        # FIX: the visible email date must match the timeline's date_str, otherwise
        # the rendered timeline order contradicts the date headers in the email
        # (the audit found 34% of seeds disagreed). Build a "Month DD, YYYY" form
        # directly from date_str so the two stay in lockstep.
        _year, _month, _day = date_str.split("-")
        date_readable = f"{MONTHS[int(_month) - 1]} {int(_day)}, {_year}"
        email_text = (
            f"From: {sender} <{sender.lower().replace(' ', '.')}@company.com>\n"
            f"To: {recipient}@company.com\n"
            f"Date: {date_readable}\n"
            f"Subject: {subject}\n\n"
            f"{body}\n"
        )
        all_entries.append((date_str, email_text))
    
    # Now add many filler emails about other topics to dilute the signal
    # We'll generate enough to reach target size
    filler_topics = [
        "Weekly sync", "Budget approval", "Hiring update", "Conference planning",
        "Vendor contract", "Office relocation", "IT outage", "Training session",
        "Performance review", "Holiday schedule", "Health benefits", "Travel policy"
    ]
    
    # We'll keep generating entries until we reach target size
    # First, sort all_entries by date (string comparison works for YYYY-MM-DD)
    all_entries.sort(key=lambda x: x[0])
    
    # Build the context by concatenating emails
    context_parts = []
    current_size = 0
    
    # Add all timeline-based emails
    for _, email_text in all_entries:
        context_parts.append(email_text)
        current_size += len(email_text)
    
    # Add filler emails until we reach target
    while current_size < target_chars:
        sender = rng.choice(people)
        # Recipient: team or individual
        if rng.random() < 0.5:
            recipient = f"{rng.choice(DEPTS).lower()} Team"
        else:
            recipient = rng.choice([p for p in people if p != sender])
        topic = rng.choice(filler_topics)
        project_filler = rng.choice(PROJECTS)
        date_filler = _rand_date(rng, 2023, 2026)
        
        filler_email = (
            f"From: {sender} <{sender.lower().replace(' ', '.')}@company.com>\n"
            f"To: {recipient.lower().replace(' ', '')}@company.com\n"
            f"Date: {date_filler}\n"
            f"Subject: {topic}: {project_filler}\n\n"
            f"Hi {recipient.split()[0] if 'Team' not in recipient else 'team'},\n\n"
            f"Just a quick update on the {topic.lower()} for {project_filler}. "
            f"We're on track for the milestones discussed last week. "
            f"Please let me know if you have any questions.\n"
            f"Thanks,\n{sender}\n"
        )
        context_parts.append(filler_email)
        current_size += len(filler_email)
    
    # Join all parts
    context = "".join(context_parts)
    
    # Trim to approximately target size (we might be slightly over)
    if len(context) > target_chars * 1.1:  # If way over, trim
        context = context[:target_chars]
        # Try to end at a clean boundary
        last_double_newline = context.rfind("\n\n")
        if last_double_newline > target_chars * 0.8:
            context = context[:last_double_newline]
    
    # Now, determine the ground truth: final owner of AI Ethics Review
    # We need to simulate the state changes from our timeline
    # Re-simulate to be sure
    final_owner = None
    final_dept = None
    
    # Process timeline in order
    for date_str, etype, owner, dept_val in timeline:
        if etype == "assign":
            final_owner = owner
            final_dept = dept_val
        elif etype == "reassign":
            final_owner = owner
            final_dept = dept_val
        elif etype == "decline":
            final_owner = None
            final_dept = None
        elif etype == "cancel":
            final_owner = None
            final_dept = None
        elif etype == "correct":
            # Corrections don't change owner unless specified (we handled dept changes in reassign/correct logic)
            # In our generation, correct only changes dept if we set it that way
            if owner is not None:  # If owner specified in correction
                final_owner = owner
                if dept_val is not None:
                    final_dept = dept_val
            # If dept_val changed but owner same, we need to update dept
            # Actually, in our timeline generation, for correct we sometimes changed dept
            # So we should update dept if dept_val is not None
            if dept_val is not None:
                final_dept = dept_val
        elif etype == "unassign":
            final_owner = None
            final_dept = None
    
    # The answer should be the final owner's name, or "Unassigned" if none
    if final_owner is None:
        ground_truth = "Unassigned"
    else:
        ground_truth = final_owner
    
    # Question
    question = (
        "After reviewing the entire email thread, who is the final owner responsible for the AI Ethics Review? "
        "If no one is currently assigned, respond with 'Unassigned'."
    )
    
    # Meta
    meta = {
        "seed": seed,
        "size": size,
        "context_chars": len(context),
        "num_emails": len(context_parts),
        "final_owner": final_owner,
        "final_dept": final_dept,
        "task_type": "temporal_coreference_resolution",
        "reasoning_required": [
            "track ownership changes over time",
            "handle corrections that override prior statements",
            "resolve coreferences like 'they', 'the lead', 'previous owner'",
            "ignore filler content about other topics",
            "integrate information distributed across the entire context"
        ]
    }
    
    return {
        "context": context,
        "question": question,
        "answer": ground_truth,
        "meta": meta
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


_R4_PERSON = _re4.compile(
    r"\b(" + "|".join(FIRST_NAMES) + r")\s+(" + "|".join(LAST_NAMES) + r")\b", _re4.IGNORECASE
)
_R4_PERSON_LF = _re4.compile(
    r"\b(" + "|".join(LAST_NAMES) + r"),\s+(" + "|".join(FIRST_NAMES) + r")\b", _re4.IGNORECASE
)
_R4_UNASSIGNED = _re4.compile(r"\bunassigned\b", _re4.IGNORECASE)
_R4_ASSIGNED = _re4.compile(r"\bassigned\b", _re4.IGNORECASE)
_R4_NOT_UNASSIGNED = _re4.compile(r"\b(?:not|never)\s+unassigned\b", _re4.IGNORECASE)
_R4_NOBODY = _re4.compile(r"\b(none|no\s+one|nobody|nothing|empty|vacant|unfilled)\b", _re4.IGNORECASE)
_R4_OWNER_IS = _re4.compile(
    r"\b(?:final|current|new|latest|now|true|actual|real)\s+(?:final\s+)?owner\s+is\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+(?:-[A-Z][a-z]+)?)"
)


def _r4_persons(text: str):
    """Occurrences of names drawn from the generator's FIRST_NAMES x LAST_NAMES pool, in
    first-last or last-first form, any case; key is 'first last' lowercased."""
    out = [(m.start(), m.end(), (m.group(1) + " " + m.group(2)).lower()) for m in _R4_PERSON.finditer(text)]
    out += [(m.start(), m.end(), (m.group(2) + " " + m.group(1)).lower()) for m in _R4_PERSON_LF.finditer(text)]
    return out


def _r4_unassigned_verdict(scope: str):
    """1.0 / 0.3 / 0.0 when scope states the position is unassigned (or nobody holds it);
    None when scope says nothing about that."""
    if _R4_NOT_UNASSIGNED.search(scope):
        return 0.0
    marks = [(m.start(), m.end(), "unassigned") for m in _R4_UNASSIGNED.finditer(scope)]
    if not marks:
        marks = [(m.start(), m.end(), "unassigned") for m in _R4_NOBODY.finditer(scope)]
    if not marks:
        return None
    # Competing candidates for the hedge test: pool names and the bare status "assigned"
    # ("Assigned or Unassigned" is an explicit alternative).
    others = _r4_persons(scope) + [(m.start(), m.end(), "assigned") for m in _R4_ASSIGNED.finditer(scope)]
    return 0.3 if _r4_hedged(scope, marks + others) else 1.0


def score(answer_text: str, truth) -> float:
    """Round-4 scorer for SELMA: grades the FINAL STATEMENT.

    - 1.0 when the truth (name in either order, any case, or "Unassigned" / "no one") is
      present and the final segment does not name a different person as the answer.
    - 0.3 when the final segment offers an explicit alternative between two candidates
      ("either X or Y").
    - 0.0 when the truth is absent, when "the final/current owner is X" names someone else
      (whole text), when "not <truth>" denies it, or when the final statement names only
      other people (a wrong final answer is wrong even if the working mentioned the truth).
    A history of earlier owners in the working is not a hedge; the word "not" is not a hedge.
    """
    if not isinstance(answer_text, str) or not answer_text.strip():
        return 0.0
    norm = _r4_normalize(answer_text).strip()
    if not norm:
        return 0.0
    low = norm.lower()
    seg = _r4_segment(norm)
    persons_seg = _r4_persons(seg)

    if truth == "Unassigned":
        verdict = _r4_unassigned_verdict(seg)
        if verdict is not None:
            return verdict
        lead = _r4_lead(norm)
        if lead:
            verdict = _r4_unassigned_verdict(lead)
            if verdict is not None:
                return verdict
        if persons_seg:
            return 0.0  # the final statement names a person instead
        verdict = _r4_unassigned_verdict(norm)
        return verdict if verdict is not None else 0.0

    truth_low = truth.lower().strip()
    truth_words = truth_low.split()
    name_variants = [truth_low]
    if len(truth_words) == 2:
        name_variants.append(truth_words[1] + ", " + truth_words[0])
    if not any(v in low for v in name_variants):
        return 0.0
    if _re4.search(r"\bnot\s+" + _re4.escape(truth_low), low):
        return 0.0
    # "the final/current owner is X" pointing at a competing candidate (whole text).
    owner_is = [s.lower() for s in _R4_OWNER_IS.findall(norm)]
    if owner_is and any(p != truth_low for p in owner_is):
        return 0.0

    # Candidates in the final segment: pool names plus "Unassigned" (a competing answer).
    def _cands(scope):
        return _r4_persons(scope) + [(m.start(), m.end(), "unassigned") for m in _R4_UNASSIGNED.finditer(scope)]

    cands = _cands(seg)
    if cands and truth_low not in {k for _, _, k in cands}:
        lead = _r4_lead(norm)
        lead_cands = _cands(lead) if lead else []
        if lead_cands and truth_low in {k for _, _, k in lead_cands}:
            seg, cands = lead, lead_cands
        else:
            return 0.0  # the final statement picks someone else (or "Unassigned")
    if cands:
        return 0.3 if _r4_hedged(seg, cands) else 1.0
    # The final segment holds no candidate (e.g. "FINLEY JONES", "Jones, Finley"): widen.
    return 0.3 if _r4_hedged(norm, _cands(norm)) else 1.0

if __name__ == "__main__":
    # Print stats for seed 0 at each size
    for size in ["small", "medium", "large"]:
        data = generate(0, size)
        print(f"=== {size.upper()} ===")
        print(f"Context length: {len(data['context']):,} characters")
        print(f"Question: {data['question']}")
        print(f"Ground truth answer: {data['answer']}")
        print(f"Meta: final owner={data['meta']['final_owner']}, dept={data['meta']['final_dept']}")
        print()
        
        # Verify scoring
        assert score(str(data["answer"]), data["answer"]) == 1.0, f"Self-score failed for {size}"
        
        # Test a few wrong answers
        wrong_answers = [
            "Unassigned" if data["answer"] != "Unassigned" else "Assigned",
            "Someone Else",
            "",
            "The team",
            "Alex Smith" if data["answer"] != "Alex Smith" else "Blake Taylor"
        ]
        for wrong in wrong_answers:
            s = score(wrong, data["answer"])
            assert s < 1.0, f"Wrong answer scored too high: '{wrong}' -> {s}"
            print(f"Wrong answer '{wrong}' scored: {s:.2f}")
        print("-" * 50)

    # ----- Defect-specific regression assertions -----
    # Original bug: a random `unassign` side-effect could fire after the last email about
    # AI Ethics, setting the truth key to "Unassigned" without producing any clear email
    # that said so; the same problem existed for the decline/cancel paths. The solver
    # looking at the latest AI Ethics email would still see a named lead in the
    # signature/declination text. The fix (1) makes unassign a dedicated email branch
    # that says "the lead position is now unassigned", and (2) makes decline/cancel
    # emails explicitly state that the position is now unassigned. This assertion proves
    # the TRUTH matches the LAST ownership-changing email for every (seed, size) cell.
    # Concretely: if the truth is "Unassigned", the most recent AI Ethics email must
    # mention "unassigned". If the truth is a name, that name must appear in the most
    # recent AI Ethics email (as the person who is now in the role).
    import re as _re_selma
    _SUBJ_PAT = _re_selma.compile(r"Subject:\s*([^\n]+)")
    _SUBJ_BACKSLASH = chr(92)
    for seed in range(10):
        for size in ["small", "medium", "large"]:
            d = generate(seed, size)
            ctx = d["context"]
            truth = d["answer"]
            # Find the most recent AI Ethics email by scanning from the end.
            last_email = None
            ix = len(ctx)
            while True:
                prev = ctx.rfind("From: ", 0, ix)
                if prev == -1:
                    break
                chunk = ctx[prev:ix]
                if "AI Ethics" in chunk:
                    last_email = chunk
                    break
                ix = prev
            assert last_email is not None, (
                "No AI Ethics email found at all (seed=" + str(seed) + ", size=" + size + ")"
            )
            _m = _SUBJ_PAT.search(last_email)
            subj_str = _m.group(1) if _m else "?"
            if truth == "Unassigned":
                assert "unassigned" in last_email.lower(), (
                    "SELMA defect: truth is 'Unassigned' but latest AI Ethics email "
                    "does not say 'unassigned' (seed=" + str(seed) + ", size=" + size + "). "
                    "Email subject: " + repr(subj_str)
                )
            else:
                assert truth in last_email, (
                    "SELMA defect: truth is " + repr(truth) + " but latest AI Ethics email "
                    "does not name them (seed=" + str(seed) + ", size=" + size + "). "
                    "Email subject: " + repr(subj_str)
                )
    print("SELMA: defect-specific assertions PASS (truth consistent with last ownership email).")

    # ----- Scorer regression: every format the audit probes must score 1.0 -----
    import json as _json_selma
    for seed in range(5):
        d = generate(seed, "small")
        truth = d["answer"]
        if truth == "Unassigned":
            positives = {
                "as_is": "Unassigned",
                "sentence": "The answer is Unassigned.",
                "bold": "**Unassigned**",
                "bold_in_sentence": "The owner is **Unassigned**.",
                "json": _json_selma.dumps({"owner": "Unassigned"}),
                "lead_in_explanation": "After applying every amendment and reversal, the owner is Unassigned.",
                "trailing_explanation": "Unassigned (after applying all corrections in the archive)",
                "final_answer_tag": "Final answer: Unassigned",
                "code_span": "`Unassigned`",
                "uppercase": "UNASSIGNED",
                "lowercase": "unassigned",
                "newline_after": "Unassigned\n",
                "quoted": '"Unassigned"',
                "sentence_currently": "The AI Ethics Review is currently unassigned.",
                "no_one": "No one is currently assigned (Unassigned).",
                "dash_explain": "Unassigned - the last owner was removed and nobody replaced them.",
                "final_owner_unassigned": "Final owner: Unassigned",
                "none": "None",
            }
        else:
            positives = {
                "as_is": truth,
                "sentence": f"The answer is {truth}.",
                "bold": f"**{truth}**",
                "bold_in_sentence": f"The owner is **{truth}**.",
                "json": _json_selma.dumps({"owner": truth}),
                "lead_in_explanation": f"After applying every amendment and reversal, the owner is {truth}.",
                "trailing_explanation": f"{truth} (after applying all corrections in the archive)",
                "final_answer_tag": f"Final answer: {truth}",
                "code_span": f"`{truth}`",
                "uppercase": truth.upper(),
                "lowercase": truth.lower(),
                "newline_after": f"{truth}\n",
                "quoted": f'"{truth}"',
                "final_owner_label": f"Final owner: {truth}",
                "with_dept": f"{truth} (Engineering)",
                "possessive": f"It is {truth}'s responsibility.",
                "md_bold_in_sentence": f"The final owner is **{truth}**.",
                "last_first": f"{truth.split()[-1]}, {truth.split()[0]}",
                "quoted_in_sentence": f"The final owner is \"{truth}\".",
                "name_then_comma": f"{truth}, who took over after the last reassignment.",
            }
        for k, s in positives.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, (
                f"SELMA positive {k!r} should score 1.0 (seed={seed}); got {sc}"
            )
    print("SELMA: scorer regression battery PASS (formats in).")

    # ----- Round 4 (issue #95): final-statement scoring -----
    # A history of earlier owners ("was assigned to X, then declined, then reassigned"), a
    # timeline table, a \boxed{} answer and the bold "The final owner ... is X from Dept."
    # sentence all score 1.0 when the final statement is right. "unassigns or reassigns" is
    # not a hedge. A final statement that names someone else is 0.0 even when the truth was
    # mentioned in the working; "either A or B" in the final segment is 0.3.
    for seed in range(5):
        d = generate(seed, "small")
        t = d["answer"]
        o = "Alex Smith" if t != "Alex Smith" else "Blake Taylor"
        o2 = "Casey Brown" if t != "Casey Brown" else "Dana Jones"
        if t == "Unassigned":
            r4_pos = {
                "history_then_final": (f"The role was first assigned to {o}, then {o} declined, then {o2} took over "
                                       f"and the review was cancelled.\n\nFinal answer: Unassigned"),
                "table_then_final": (f"| Date | Event | Owner |\n|---|---|---|\n| 2024-01-01 | assigned | {o} |\n"
                                     f"| 2025-01-01 | reassigned | {o2} |\n| 2026-01-01 | cancelled | Unassigned |\n\n"
                                     f"**Final owner: Unassigned**"),
                "boxed": "\\boxed{\\text{Unassigned}}",
                "assigns_or_reassigns": (f"The last email (from {o}) says the position is now unassigned, and no later "
                                         f"email assigns or reassigns the role."),
                "answer_first_then_explanation": (f"**Unassigned**\n\nThe last email, from {o}, cancelled the review "
                                                  f"after {o2} had declined the role."),
                "therefore_line": (f"{o} was assigned, then declined.\n\nTherefore, the final owner is: **Unassigned**."),
                "not_in_working": (f"The correction says the review is under Legal, not Compliance, and {o} declined.\n\n"
                                   f"**Unassigned**"),
            }
            r4_neg = {
                "either_in_final": (f"Final answer: either {o} or Unassigned", 0.3),
                "wrong_final_truth_in_working": (f"The thread says the position was unassigned at one point.\n\n"
                                                 f"Final answer: {o}", 0.0),
                "not_unassigned": (f"It is not unassigned; the owner is {o}.", 0.0),
            }
        else:
            r4_pos = {
                "history_then_final": (f"The role was first assigned to {o}, then {o} declined, then {o2} took over, "
                                       f"then it was reassigned.\n\nFinal answer: {t}"),
                "table_then_final": (f"| Date | Event | Owner |\n|---|---|---|\n| 2024-01-01 | assigned | {o} |\n"
                                     f"| 2025-01-01 | declined | Unassigned |\n| 2026-01-01 | assigned | {t} |\n\n"
                                     f"**Final owner: {t}**"),
                "boxed": f"\\boxed{{\\text{{{t}}}}}",
                "unassigns_or_reassigns": (f"The most recent assignment email (from {o}) assigns the review to **{t}**, "
                                           f"and no subsequent email unassigns or reassigns the role."),
                "bold_final_sentence_with_dept": f"**The final owner responsible for the AI Ethics Review is {t} from Operations.**",
                "answer_first_then_explanation": (f"**{t}**\n\nThe last email, from {o}, confirmed the assignment after "
                                                  f"{o2} had declined the role."),
                "not_in_working": (f"The correction says the review is under Legal, not Compliance; {t} remains the lead.\n\n"
                                   f"**{t}**"),
                "quoted_email_then_final": (f"The latest email, from {o}, states:\n\n> \"Effective immediately, {t} from "
                                            f"Marketing will be taking over.\"\n\nThe final owner is **{t}** (from Marketing)."),
            }
            r4_neg = {
                "either_in_final": (f"Final answer: either {o} or {t}", 0.3),
                "wrong_final_truth_in_working": (f"The thread names {t} as lead at one point.\n\nFinal answer: {o}", 0.0),
                "owner_is_other": (f"Ownership moved from {t} to {o}; the final owner is {o}.", 0.0),
                "unassigned_final_truth_in_working": (f"{t} was assigned on May 1.\n\nFinal answer: Unassigned", 0.0),
            }
        for k, s in r4_pos.items():
            sc = score(s, t)
            assert sc == 1.0, f"SELMA round-4 positive {k!r} should score 1.0 (seed={seed}, truth={t!r}); got {sc}"
        for k, (s, want) in r4_neg.items():
            sc = score(s, t)
            assert sc == want, f"SELMA round-4 negative {k!r} should score {want} (seed={seed}, truth={t!r}); got {sc}"
    print("SELMA: round-4 final-statement assertions PASS (history is not a hedge; wrong finals stay wrong).")
