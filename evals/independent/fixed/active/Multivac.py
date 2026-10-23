"""Multivac - long-context eval (scorer fix).

generate() is byte-identical to the original; only score() is updated.
"""

import random
import re
from collections import defaultdict


class ProjectSpecGenerator:
    def __init__(self, seed, size):
        self.rng = random.Random(seed)
        self.size = size
        self.requirements = self._generate_initial_requirements()
        self.events = []
        self._generate_timeline()
        self.current_state = self._compute_current_state()

    def _generate_initial_requirements(self):
        num_reqs = self.rng.randint(5, 8)
        reqs = {}
        for i in range(num_reqs):
            req_id = "R" + str(i + 1)
            desc = self.rng.choice([
                "User authentication", "Data encryption", "Reporting module",
                "API integration", "User interface", "Database migration",
                "Accessibility compliance", "Performance optimization",
            ])
            details = self.rng.choice([
                "using OAuth 2.0", "with AES-256", "for sales data",
                "with Partner X", "dark mode support", "from SQL to NoSQL",
                "WCAG 2.1 AA", "sub-second response times",
            ])
            reqs[req_id] = {
                "description": desc + " " + details,
                "status": "Pending",
                "priority": self.rng.choice(["High", "Medium", "Low"]),
                "version": 1,
                "last_updated": 0,
            }
        return reqs

    def _generate_timeline(self):
        num_events = {"small": 600, "medium": 2900, "large": 11500}[self.size]
        for step in range(num_events):
            event_type = self.rng.choices(
                ["update", "clarification", "override", "new", "discussion"],
                weights=[0.3, 0.2, 0.1, 0.2, 0.2],
            )[0]

            if event_type == "update" and self.requirements:
                req_id = self.rng.choice(list(self.requirements.keys()))
                req = self.requirements[req_id]
                old_status = req["status"]
                new_status = self.rng.choice(["In Progress", "Completed", "Blocked", "On Hold"])
                req["status"] = new_status
                req["version"] += 1
                req["last_updated"] = step
                self.events.append({
                    "type": "update",
                    "req_id": req_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "version": req["version"],
                    "step": step,
                })

            elif event_type == "clarification" and self.requirements:
                req_id = self.rng.choice(list(self.requirements.keys()))
                req = self.requirements[req_id]
                clarification = self.rng.choice([
                    "Must use open-source libraries",
                    "Needs to support mobile devices",
                    "Should be backwards compatible",
                    "Security review required",
                    "User training materials needed",
                ])
                req["description"] = req["description"] + " (" + clarification + ")"
                req["version"] += 1
                req["last_updated"] = step
                self.events.append({
                    "type": "clarification",
                    "req_id": req_id,
                    "clarification": clarification,
                    "version": req["version"],
                    "step": step,
                })

            elif event_type == "override" and len(self.requirements) >= 2:
                req_id1, req_id2 = self.rng.sample(list(self.requirements.keys()), 2)
                req1 = self.requirements[req_id1]
                req2 = self.requirements[req_id2]
                override_desc = self.rng.choice([
                    req_id1 + " now depends on " + req_id2,
                    req_id2 + " supersedes " + req_id1,
                    req_id1 + " and " + req_id2 + " merged into new requirement",
                ])

                if "supersedes" in override_desc:
                    req1["status"] = "Obsolete"
                    req2["description"] = req2["description"] + " (incorporates " + req_id1 + ")"
                elif "merged" in override_desc:
                    new_id = "R" + str(len(self.requirements) + 1)
                    self.requirements[new_id] = {
                        "description": "Merged: " + req1["description"] + " and " + req2["description"],
                        "status": "Pending",
                        "priority": "High",
                        "version": 1,
                        "last_updated": step,
                    }
                    req1["status"] = "Obsolete"
                    req2["status"] = "Obsolete"
                else:
                    req1["description"] = req1["description"] + " (depends on " + req_id2 + ")"

                self.events.append({
                    "type": "override",
                    "req_ids": [req_id1, req_id2],
                    "override_desc": override_desc,
                    "step": step,
                })

            elif event_type == "new":
                new_id = "R" + str(len(self.requirements) + 1)
                desc = self.rng.choice([
                    "Localization", "Automated testing", "Documentation",
                    "Scalability improvements", "User feedback system",
                ])
                details = self.rng.choice([
                    "for 5 languages", "with 80% coverage", "user manuals",
                    "to handle 10x load", "in-app surveys",
                ])
                self.requirements[new_id] = {
                    "description": desc + " " + details,
                    "status": "Pending",
                    "priority": self.rng.choice(["High", "Medium", "Low"]),
                    "version": 1,
                    "last_updated": step,
                }
                self.events.append({
                    "type": "new",
                    "req_id": new_id,
                    "description": self.requirements[new_id]["description"],
                    "step": step,
                })

            else:
                topics = ["budget", "timeline", "staffing", "risks", "quality"]
                topic = self.rng.choice(topics)
                content_pick = self.rng.choice([
                    topic.capitalize() + " concerns raised by stakeholder",
                    "Meeting scheduled to discuss " + topic,
                    "New " + topic + " constraints identified",
                    topic.capitalize() + " update from management",
                ])
                self.events.append({
                    "type": "discussion",
                    "topic": topic,
                    "content": content_pick,
                    "step": step,
                })

    def _compute_current_state(self):
        current = {}
        for req_id, req in self.requirements.items():
            if req["status"] != "Obsolete":
                current[req_id] = {
                    "description": req["description"],
                    "status": req["status"],
                    "priority": req["priority"],
                }
        return current

    def _generate_context(self):
        sections = []
        sections.append("Project Requirements Document")
        sections.append("=" * 40)
        sections.append("This document outlines the requirements for Project Phoenix.")
        sections.append("")
        sections.append("Initial Requirements:")
        for req_id, req in self.requirements.items():
            sections.append("- " + req_id + ": " + req["description"] + " (Status: " + req["status"] + ", Priority: " + req["priority"] + ")")
        sections.append("")
        for event in self.events:
            if event["type"] == "update":
                sections.append("Update (Step " + str(event["step"]) + "): Requirement " + event["req_id"] + " status changed from " + event["old_status"] + " to " + event["new_status"] + " (v" + str(event["version"]) + ").")
            elif event["type"] == "clarification":
                sections.append("Clarification (Step " + str(event["step"]) + "): Requirement " + event["req_id"] + " updated with: " + event["clarification"] + " (v" + str(event["version"]) + ").")
            elif event["type"] == "override":
                sections.append("Override (Step " + str(event["step"]) + "): " + event["override_desc"] + ".")
            elif event["type"] == "new":
                sections.append("New Requirement (Step " + str(event["step"]) + "): " + event["req_id"] + " - " + event["description"] + ".")
            elif event["type"] == "discussion":
                sections.append("Discussion (Step " + str(event["step"]) + "): " + event["content"] + ".")
            sections.append("")
        sections.append("End of Document")
        return "\n".join(sections)

    def pick_target_requirement(self):
        req_ids = list(self.current_state.keys())
        return self.rng.choice(req_ids)

    def get_question(self, target_req):
        return "What is the current status and full description of requirement " + target_req + "?"

    def get_answer(self, target_req):
        req = self.current_state[target_req]
        return {
            "req_id": target_req,
            "status": req["status"],
            "description": req["description"],
        }

    def get_meta(self):
        return {
            "num_initial_reqs": len(self.requirements),
            "num_events": len(self.events),
            "num_current_reqs": len(self.current_state),
        }


def generate(seed, size):
    if size not in {"small", "medium", "large"}:
        raise ValueError("size must be small, medium, or large")
    gen = ProjectSpecGenerator(seed, size)
    target_req = gen.pick_target_requirement()
    return {
        "context": gen._generate_context(),
        "question": gen.get_question(target_req),
        "answer": gen.get_answer(target_req),
        "meta": gen.get_meta(),
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


_KNOWN_STATUSES = [
    "Pending", "In Progress", "Completed", "Blocked", "On Hold",
    "Rejected", "Approved", "Obsolete",
]
_STATUS_LABEL_RE = re.compile(r"\b(?:current\s+)?status\b", re.IGNORECASE)
# Round 4: a "status" label that refers to history, not to the answer. "the original listed
# status was X" / "earlier status: X" / "Status history:" are working, not the final statement.
_HIST_BEFORE_RE = re.compile(
    r"\b(?:original(?:ly)?|previous(?:ly)?|earlier|initial(?:ly)?|prior|old|former(?:ly)?|"
    r"past|first)\b(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)
_HIST_AFTER_RE = re.compile(
    r"^\s*(?:history|histories|changes?|change\s+log|timeline|log|transitions?|updates|progression)\b",
    re.IGNORECASE,
)
# Round 4 rule 4: a candidate that the text itself rules out -- "not X", "from X to Y",
# "originally X", "instead of X" -- is skipped when picking the authoritative value.
_NEG_BEFORE_RE = re.compile(
    r"\b(?:not|from|instead\s+of|rather\s+than|original(?:ly)?|previous(?:ly)?|initial(?:ly)?|"
    r"earlier|former(?:ly)?|no\s+longer|never)\s*(?:set\s+to\s+|listed\s+as\s+|at\s+|in\s+)?[\"'“‘(]?\s*$",
    re.IGNORECASE,
)
_STATUS_ALT = "|".join(re.escape(s.lower()) for s in _KNOWN_STATUSES)
# "X -> Y", "X → Y", "X to Y", "X (v2), then changed to Y at Step 9": X is the superseded
# value. Step/version annotations between X and the arrow are stripped before matching.
_TRANSITION_AFTER_RE = re.compile(
    r"^[\"'”’)]?\s*(?:->|→|=>|⇒|,?\s*(?:and\s+)?(?:then|later|subsequently|finally|eventually)?\s*,?\s*"
    r"(?:it\s+)?(?:was\s+)?(?:changed|moved|updated|switched|set|reverted|went)?\s*(?:back\s+)?to)\s+"
    r"[\"'“‘]?(?:" + _STATUS_ALT + r")\b",
    re.IGNORECASE,
)
_ANNOT_RE = re.compile(
    r"\([^()]{0,60}\)|\b(?:at|in|on|by|since|as\s+of)\s+(?:update\s+|the\s+)?step\s+\d+\b|,?\s*\bv\d+\b",
    re.IGNORECASE,
)


def _is_transition_source(after):
    after = _ANNOT_RE.sub(" ", after)
    after = re.sub(r"\s+", " ", after)
    return _TRANSITION_AFTER_RE.match(after) is not None


def _status_window(norm, m):
    """Candidates (pos, status) in the 120-char window after a status label, with rule-4 skips."""
    window = norm[m.end():m.end() + 120]
    cands = []
    for k in (s.lower() for s in _KNOWN_STATUSES):
        for km in re.finditer(r"\b" + re.escape(k) + r"\b", window):
            before = norm[max(0, m.end() + km.start() - 24):m.end() + km.start()]
            if _NEG_BEFORE_RE.search(before):
                continue
            if _is_transition_source(norm[m.end() + km.end():m.end() + km.end() + 90]):
                continue
            cands.append((km.start(), k))
    cands.sort()
    return window, cands


def score(answer_text, truth):
    """Robust to formatting, strict about substance; round 4 grades the final statement.

    1.0 only when both the requirement's status and its full description are
    stated correctly (case- and whitespace-insensitive). 0.3 when the
    authoritative status window hedges between two statuses and one of them
    is the truth (or the description is right); 0.2 if exactly one of the two
    is found. 0.0 otherwise.

    Round 4 (issue #95): the text is formatting-normalised first; the
    authoritative status is the LAST "status" label whose window holds a known
    status, preferring a label inside the final segment, skipping labels that
    introduce history ("the original status was", "Status history:") and
    candidates the text rules out ("from X to Y", "originally X", "not X").
    The per-window hedge (two distinct statuses in the same paragraph) stays.
    A line break right after the description is a boundary.
    """
    if not isinstance(answer_text, str):
        return 0.0
    if not isinstance(truth, dict):
        return 0.0

    req_id = truth.get("req_id", "")
    expected_status = truth.get("status", "").lower()
    expected_desc = truth.get("description", "").lower()

    if not req_id or not expected_status or not expected_desc:
        return 0.0
    text = _r4_normalize(answer_text)
    # Match the requirement id with optional whitespace between the letter and
    # the digits ("R 7" matches "R7").
    # Round 3.1 (#63): bounded on both sides, so truth "R14" is not matched
    # by an answer about "R142" (or "R7" by "R70").
    rid_alt = r"(?<![A-Za-z0-9])" + re.escape(req_id[0]) + " ?" + re.escape(req_id[1:]) + r"(?![0-9])"
    if not re.search(rid_alt, text):
        return 0.0

    norm = text.lower()

    desc_norm = re.sub(r"\s+", " ", expected_desc).strip()
    desc_in_norm = re.sub(r"\s+", " ", norm).strip()
    desc_found_at = desc_in_norm.find(desc_norm)
    desc_found = desc_found_at >= 0
    desc_clean = False
    if desc_found:
        # Require the description to be a bounded phrase, not a fragment
        # glued onto extra text. After the match, allow end-of-string,
        # sentence punctuation, structural close, OR a "(label)" paren
        # that is clearly a structural reference (e.g. "(requirement R42)").
        # Reject fabrication parens like "(Must also support offline mode)".
        end_idx = desc_found_at + len(desc_norm)
        tail = desc_in_norm[end_idx:]
        # Markdown emphasis/code closers right after the description
        # ("**<desc>** — Status: ...") are formatting, not content.
        stripped = re.sub(r"^[*_`]+", "", tail.lstrip()).lstrip()
        # Round 3.1 (#63): the description may be followed by another field
        # of the same answer -- "<desc> — Status: X", "<desc>\n- **Current
        # Status:** X", "<desc> | Priority: Low" -- with an optional dash,
        # bar or bullet separator. Only a field LABEL qualifies, so "<desc> —
        # must also support mobile" stays a fabrication.
        field_after = re.match(
            r"^(?:[-–—|•·]\s*)?[*_`]*"
            r"(?:current\s+)?(?:status|priority|state)\b[*_`]*\s*[*_`]*"
            r"(?::|=|-|–|—|\bis\b|\bwas\b)",
            stripped,
        )
        # Round 4: a line break right after the description is a boundary (the
        # whitespace collapse above erased it). Checked on a newline-preserving
        # copy so "<desc>\n\nHistory: ..." is bounded and "<desc> (Must also ...)"
        # is still a fabrication.
        nl_norm = re.sub(r"[ \t\r\f\v]+", " ", norm)
        nl_norm = re.sub(r" ?\n ?", "\n", nl_norm).strip()
        nl_at = nl_norm.find(desc_norm)
        nl_break = nl_at >= 0 and re.match(r"^[*_`]*[ \t]*(?:\n|$)", nl_norm[nl_at + len(desc_norm):]) is not None
        if field_after:
            desc_clean = True
        elif not stripped:
            desc_clean = True
        elif nl_break:
            desc_clean = True
        elif stripped[0] in ".!?;:\n}])\"'”|":
            desc_clean = True
        elif stripped[0] == "(":
            # Structural references: "(requirement R12)", "(see ...)", "(note ...)",
            # "(e.g. ...)", "(for ...)", "(ref ...)", "(appendix ...)", etc.
            # Reject if the paren introduces additional requirements or clarifications.
            paren_inner = stripped[1:].split(")", 1)[0].lower().strip()
            paren_inner = re.sub(r"^[*_`]+", "", paren_inner)
            structural_starts = (
                "requirement", "see ", "note", "e.g", "for ", "ref ", "ref.",
                "appendix", "see also", "see:",
                # Round 3.1 (#63): "<desc> (Status: X)" carries a field of
                # the answer, not extra description content.
                "status", "current status", "priority",
            )
            fabrication_starts = (
                "must", "should", "will", "may", "shall", "need", "needs",
                "also", "additionally", "plus", "and ", "with ", "including",
                "however", "but ", "yet ",
            )
            if any(paren_inner.startswith(s) for s in fabrication_starts):
                desc_clean = False
            elif any(paren_inner.startswith(s) for s in structural_starts):
                desc_clean = True
            else:
                # Unknown paren: treat as fabrication to be safe.
                desc_clean = False
        else:
            # Allow new sentence boundary like ". " or ".\n".
            desc_clean = re.match(r"^[.!?:;,]\s", tail) is not None

    status_found = False
    status_hedged = False
    status_alternate = False

    # Round 4: the authoritative "status" label is the LAST one whose window
    # holds a known status, preferring labels inside the final segment. Labels
    # that introduce history are skipped; ruled-out candidates ("from X to Y",
    # "originally X") are skipped inside each window; a hedge is two distinct
    # surviving candidates in the same paragraph of that window.
    segment = _r4_segment(text)
    seg_start = text.rstrip().rfind(segment) if segment else len(text)
    labels = []
    for m in _STATUS_LABEL_RE.finditer(norm):
        before = norm[max(0, m.start() - 30):m.start()]
        if _HIST_BEFORE_RE.search(before):
            continue
        if _HIST_AFTER_RE.match(norm[m.end():m.end() + 20]):
            continue
        window, cands = _status_window(norm, m)
        if not cands:
            continue
        labels.append((m.start() >= seg_start, window, cands))
    if labels:
        in_seg = [l for l in labels if l[0]]
        _, window, cands = (in_seg or labels)[-1]
        first = cands[0][1]
        # Round 3.1 (#63): a paragraph break ends the status field. A
        # later paragraph's history ("The status was originally set to
        # Pending ...") is not a second candidate; a hedge on the same
        # line or in the same paragraph still is.
        cut = window.find("\n\n", cands[0][0])
        others = []
        for p, c in cands[1:]:
            if (cut < 0 or p < cut) and c != first and c not in others:
                others.append(c)
        if first == expected_status and not others:
            status_found = True
        else:
            status_hedged = True
            if expected_status in (first, *others):
                status_alternate = True

    if status_found and desc_clean:
        return 1.0
    # Hedged status (multiple candidates named) caps the score below 0.5
    # so the audit battery does not flag a hedge as a near-correct answer.
    if status_hedged and (status_alternate or desc_clean):
        return 0.3
    # Only one of the two core answers (status, full description) is correct.
    # Treat as wrong-answer partial credit at 0.2 — well below 0.5 to keep
    # the audit battery from flagging a missing piece as a near-miss.
    if status_found or desc_clean:
        return 0.2
    # No correct substance found.
    return 0.0

if __name__ == "__main__":
    import re as _re
    import json as _json
    for size in ["small", "medium", "large"]:
        data = generate(0, size)
        print("Size:", size)
        print("Context length:", len(data["context"]), "characters")
        print("Question:", data["question"])
        print("Truth:", data["answer"])
        print()
        truth_str = "Requirement " + data["answer"]["req_id"] + ": Status: " + data["answer"]["status"] + ", Description: " + data["answer"]["description"]
        assert score(truth_str, data["answer"]) == 1.0
        wrong_status = "Completed" if data["answer"]["status"] != "Completed" else "Pending"
        wrong_answer1 = "Requirement " + data["answer"]["req_id"] + ": Status: " + wrong_status + ", Description: " + data["answer"]["description"]
        assert score(wrong_answer1, data["answer"]) < 1.0
        wrong_desc = "This is an incorrect description"
        wrong_answer2 = "Requirement " + data["answer"]["req_id"] + ": Status: " + data["answer"]["status"] + ", Description: " + wrong_desc
        assert score(wrong_answer2, data["answer"]) < 1.0
        print("All tests passed for", size)
        print("-" * 50)

    for seed in range(10):
        for size in ["small", "medium", "large"]:
            d = generate(seed, size)
            m = _re.search(r"requirement (R\d+)", d["question"])
            assert m is not None, "Question has no requirement id (seed=" + str(seed) + ", size=" + size + ")"
            asked = m.group(1)
            answered = d["answer"]["req_id"]
            assert asked == answered, (
                "Multivac defect: asked-about " + asked + " != answered " + answered +
                " (seed=" + str(seed) + ", size=" + size + ")"
            )
    print("Multivac: defect-specific assertions PASS (asked == answered for every seed/size).")


    for seed in range(5):
        d = generate(seed, "small")
        rid = d["answer"]["req_id"]
        st = d["answer"]["status"]
        de = d["answer"]["description"]
        positives = {
            "str_dict": str(d["answer"]),
            "status_colon": rid + "\nStatus: " + st + "\nDescription: " + de,
            "sentence_is": "The current status of " + rid + " is " + st + ", and its full description is: " + de,
            "sentence_status_is": rid + " status is " + st + ". Description: " + de,
            "md_bold_labels": "**" + rid + "**\n**Status:** " + st + "\n**Description:** " + de,
            "md_bullets_bold": "- **Status**: " + st + "\n- **Description**: " + de + "\n(requirement " + rid + ")",
            "json": _json.dumps({"requirement": rid, "status": st, "description": de}),
            "quoted_status": rid + " - Status: \"" + st + "\"; Description: \"" + de + "\"",
            "status_dash": rid + ": Status - " + st + "; Description - " + de,
            "table": "| Requirement | Status | Description |\n|---|---|---|\n| " + rid + " | " + st + " | " + de + " |",
            "lower_status": rid + "\nstatus: " + st.lower() + "\ndescription: " + de,
            "desc_trailing_period": rid + "\nStatus: " + st + "\nDescription: " + de + ".",
            "desc_collapsed_space": rid + "\nStatus: " + st + "\nDescription: " + _re.sub(" +", " ", de),
            "rid_spaced": "Requirement R " + rid[1:] + "\nStatus: " + st + "\nDescription: " + de,
            "after_status_phrase": "After walking every status change for " + rid + " the current status is " + st + "; description: " + de,
        }
        for k, s in positives.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, (
                "Multivac positive " + repr(k) + " should score 1.0 (seed=" + str(seed) + "); got " + str(sc)
            )
        wrong_st = next(s for s in _KNOWN_STATUSES if s.lower() != st.lower())
        s_partial = rid + "\nStatus: " + st + "\nDescription: " + de[:max(5, len(de)//2)]
        assert score(s_partial, d["answer"]) < 1.0
        s_shotgun = rid + "\nStatus: " + wrong_st + " (earlier status: " + st + ")\nDescription: " + de
        assert score(s_shotgun, d["answer"]) < 1.0
        s_hedge = rid + "\nStatus: " + wrong_st + " or " + st + "\nDescription: " + de
        assert score(s_hedge, d["answer"]) < 1.0

        # Round 4 (issue #95): the final statement is graded, formatting-normalised; shown
        # working before (or history after) the answer is not a hedge.
        other2 = next(s for s in _KNOWN_STATUSES if s.lower() not in (st.lower(), wrong_st.lower()))
        r4_positives = {
            # markdown table of the walk, ending in the answer row
            "table_history_then_final": (
                "| Step | Status |\n|---|---|\n| 12 | " + wrong_st + " |\n| 88 | " + other2 + " |\n| 140 | " + st + " |\n\n"
                "**Final answer:** " + rid + " — Status: **" + st + "**. Description: " + de
            ),
            # LaTeX-ish boxed answer
            "boxed": "Walked the log for " + rid + ".\n\n$$\\boxed{\\text{Status: " + st + "}}$$\n\nDescription: " + de,
            # history paragraph ("was X, then Y") followed by the final answer
            "history_then_final": (
                "Requirement " + rid + " was " + wrong_st + " at Step 40, then " + other2 + " at Step 200, "
                "then changed to " + st + " at Step 410.\n\n"
                "Final answer:\nStatus: " + st + "\nDescription: " + de
            ),
            # the answer first, a history paragraph after it (the plain-arm house style)
            "answer_then_history_paragraph": (
                "**Requirement " + rid + "**\n\n- **Status:** " + st + "\n- **Full Description:** " + de + "\n\n"
                "The status was set to \"" + st + "\" at Step 243 (changed from " + wrong_st + " to " + st + ", v3)."
            ),
            # status trailer quoting the transition that produced it
            "status_with_transition_trailer": (
                rid + ": " + de + "\n\n**Current Status:** **" + st + "** (last changed at Step 2398: "
                "\"Requirement " + rid + " status changed from " + wrong_st + " to " + st + " (v4)\")"
            ),
            # arrow-chain history line in the same paragraph as the answer
            "arrow_chain_same_paragraph": (
                rid + " — Description: \"" + de + "\". Current status: " + st + " (Priority: Low). "
                "Status history: " + wrong_st + " -> " + other2 + " (Step 446) -> " + st + " (Step 974)."
            ),
            # description on its own line, a paragraph of notes after it
            "desc_line_then_notes": (
                rid + "\nStatus: " + st + "\nDescription: " + de + "\n\n"
                "Notes: no status change was ever applied after Step 900."
            ),
        }
        for k, s in r4_positives.items():
            sc = score(s, d["answer"])
            assert sc == 1.0, "Multivac round-4 positive " + repr(k) + " should score 1.0 (seed=" + str(seed) + "); got " + str(sc)
        r4_negatives = {
            # the final segment offers an explicit alternative
            "final_either_or": (
                "History: " + wrong_st + " at Step 3, " + st + " at Step 90.\n\n"
                "Final answer: " + rid + " is either " + st + " or " + wrong_st + ". Description: " + de
            ),
            # the final segment names the wrong status while the working mentions the right one
            "final_wrong_working_right": (
                "At Step 90 the log says \"" + rid + " status changed from " + wrong_st + " to " + st + "\".\n\n"
                "Final answer: " + rid + "\nStatus: " + wrong_st + "\nDescription: " + de
            ),
            # a trailing history sentence names the truth, the answer line is wrong
            "wrong_answer_truth_in_history": (
                rid + ": " + de + "\n\n**Current Status: " + wrong_st + "**\n\n"
                "Prior to that it was " + other2 + ", and the original listed status was \"" + st + ".\""
            ),
        }
        for k, s in r4_negatives.items():
            sc = score(s, d["answer"])
            assert sc < 1.0, "Multivac round-4 negative " + repr(k) + " should score < 1.0 (seed=" + str(seed) + "); got " + str(sc)
    print("Multivac: scorer regression battery PASS (formats in/hedges out; round-4 final-statement cases).")
