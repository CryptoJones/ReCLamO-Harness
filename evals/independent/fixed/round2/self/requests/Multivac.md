# Task: author ONE independent long-context evaluation task (as a runnable Python generator)

You are helping evaluate a "Recursive Language Model" (RLM) harness. The system under test receives
two strings — a very long CONTEXT and a QUESTION — and returns an ANSWER string. Internally it may run
code over the context and call a language model on pieces of it, but you should treat it as a black box.
The model behind it has a ~32K-token working window; contexts will be far larger than that.

The harness authors wrote their own tests, and we suspect those tests are too easy and shaped to the
harness. We want tests written by someone else: you. Do NOT try to guess how the harness works and do
not design around it. Design a task that a careful human analyst with plenty of time would get right,
but that is genuinely hard to get right without actually reading and reasoning over much of the context.

## Requirements (all mandatory)
1. Deliver a SINGLE self-contained Python 3.11 file in one ```python code block. Standard library only.
2. It must expose: `generate(seed: int, size: str) -> dict` returning
   `{"context": str, "question": str, "answer": <ground truth>, "meta": {...}}`
   with `size` in {"small", "medium", "large"} giving roughly 60K, 300K and 1.2M characters of context.
   And `score(answer_text: str, truth) -> float` in [0, 1], robust to formatting (case, punctuation,
   ordering, extra prose) but NOT lenient about the substance.
3. Fully deterministic given the seed (use `random.Random(seed)`, no time, no network, no files).
4. Ground truth must be computed by the generator from its own data structures — never hand-written.
5. **Grep-resistant**: the answer must not be recoverable by keyword search, regex, or simple counting
   of surface tokens. Use paraphrase, varied vocabulary, distractors, negations, coreference
   ("the latter", "her manager"), corrections later in the text that override earlier statements,
   and facts whose meaning depends on other parts of the document. State in a comment WHY a regex /
   keyword approach fails on your task.
6. **Requires breadth**: the correct answer must depend on information spread across the whole
   context (aggregation, multi-hop joins, temporal reasoning, consistency checking, etc.), not one spot.
7. Natural-looking prose or semi-structured text (emails, logs, minutes, reports, chat) — not
   obviously synthetic key=value lines.
8. Include a short `if __name__ == "__main__":` that prints size stats, the question and the truth for
   seed 0 at each size, and asserts `score(str(truth), truth) == 1.0` and that a few wrong answers score < 1.

## Deliverable format
- One paragraph: the task, what skill it tests, why it is hard, and the main way a solver would fail.
- The single ```python block.
- Nothing else. Do not read or modify any files; you do not need tools for this.


---

# Revision request (round 2)

The generator below is the version of your task currently used for evaluation. A real evaluation run found this defect in it:

**The answer key never matches the question: get_question() and get_answer() each call rng.choice separately, so the key describes a different requirement than the one the question asks about. It mismatched in all 18 seed x size combinations checked (seeds 0-5, all sizes). Choose the target requirement ONCE per generate() call and use it for both the question and the answer. Add a self-test assertion that the requirement named in the question is the one whose lineage the answer describes, for seeds 0-9 at every size.**

Return a corrected version that still satisfies the whole brief (sizes ~60K/300K/1.2M, deterministic across processes, standard library only, Python 3.11 compatible: no backslashes inside f-string expressions). Keep the same task idea, question style and difficulty; change only what the defect requires. Same deliverable format: one paragraph (mention what you changed) then the single complete ```python block.

## Current generator

```python
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
            req_id = f"R{i+1}"
            desc = self.rng.choice([
                "User authentication", "Data encryption", "Reporting module",
                "API integration", "User interface", "Database migration",
                "Accessibility compliance", "Performance optimization"
            ])
            details = self.rng.choice([
                "using OAuth 2.0", "with AES-256", "for sales data",
                "with Partner X", "dark mode support", "from SQL to NoSQL",
                "WCAG 2.1 AA", "sub-second response times"
            ])
            reqs[req_id] = {
                "description": f"{desc} {details}",
                "status": "Pending",
                "priority": self.rng.choice(["High", "Medium", "Low"]),
                "version": 1,
                "last_updated": 0
            }
        return reqs

    def _generate_timeline(self):
        num_events = {"small": 600, "medium": 2900, "large": 11500}[self.size]
        for step in range(num_events):
            event_type = self.rng.choices(
                ["update", "clarification", "override", "new", "discussion"],
                weights=[0.3, 0.2, 0.1, 0.2, 0.2]
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
                    "step": step
                })

            elif event_type == "clarification" and self.requirements:
                req_id = self.rng.choice(list(self.requirements.keys()))
                req = self.requirements[req_id]
                clarification = self.rng.choice([
                    "Must use open-source libraries",
                    "Needs to support mobile devices",
                    "Should be backwards compatible",
                    "Security review required",
                    "User training materials needed"
                ])
                req["description"] += f" ({clarification})"
                req["version"] += 1
                req["last_updated"] = step
                self.events.append({
                    "type": "clarification",
                    "req_id": req_id,
                    "clarification": clarification,
                    "version": req["version"],
                    "step": step
                })

            elif event_type == "override" and len(self.requirements) >= 2:
                req_id1, req_id2 = self.rng.sample(list(self.requirements.keys()), 2)
                req1 = self.requirements[req_id1]
                req2 = self.requirements[req_id2]
                
                override_desc = self.rng.choice([
                    f"{req_id1} now depends on {req_id2}",
                    f"{req_id2} supersedes {req_id1}",
                    f"{req_id1} and {req_id2} merged into new requirement"
                ])
                
                if "supersedes" in override_desc:
                    req1["status"] = "Obsolete"
                    req2["description"] += f" (incorporates {req_id1})"
                elif "merged" in override_desc:
                    new_id = f"R{len(self.requirements)+1}"
                    self.requirements[new_id] = {
                        "description": f"Merged: {req1['description']} and {req2['description']}",
                        "status": "Pending",
                        "priority": "High",
                        "version": 1,
                        "last_updated": step
                    }
                    req1["status"] = "Obsolete"
                    req2["status"] = "Obsolete"
                    req_id = new_id
                else:
                    req1["description"] += f" (depends on {req_id2})"
                
                self.events.append({
                    "type": "override",
                    "req_ids": [req_id1, req_id2],
                    "override_desc": override_desc,
                    "step": step
                })

            elif event_type == "new":
                new_id = f"R{len(self.requirements)+1}"
                desc = self.rng.choice([
                    "Localization", "Automated testing", "Documentation",
                    "Scalability improvements", "User feedback system"
                ])
                details = self.rng.choice([
                    "for 5 languages", "with 80% coverage", "user manuals",
                    "to handle 10x load", "in-app surveys"
                ])
                self.requirements[new_id] = {
                    "description": f"{desc} {details}",
                    "status": "Pending",
                    "priority": self.rng.choice(["High", "Medium", "Low"]),
                    "version": 1,
                    "last_updated": step
                }
                self.events.append({
                    "type": "new",
                    "req_id": new_id,
                    "description": self.requirements[new_id]["description"],
                    "step": step
                })

            else:
                topics = ["budget", "timeline", "staffing", "risks", "quality"]
                topic = self.rng.choice(topics)
                content = self.rng.choice([
                    f"{topic.capitalize()} concerns raised by stakeholder",
                    f"Meeting scheduled to discuss {topic}",
                    f"New {topic} constraints identified",
                    f"{topic.capitalize()} update from management"
                ])
                self.events.append({
                    "type": "discussion",
                    "topic": topic,
                    "content": content,
                    "step": step
                })

    def _compute_current_state(self):
        current = {}
        for req_id, req in self.requirements.items():
            if req["status"] != "Obsolete":
                current[req_id] = {
                    "description": req["description"],
                    "status": req["status"],
                    "priority": req["priority"]
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
            sections.append(f"- {req_id}: {req['description']} (Status: {req['status']}, Priority: {req['priority']})")
        sections.append("")

        for event in self.events:
            if event["type"] == "update":
                sections.append(f"Update (Step {event['step']}): Requirement {event['req_id']} status changed from {event['old_status']} to {event['new_status']} (v{event['version']}).")
            elif event["type"] == "clarification":
                sections.append(f"Clarification (Step {event['step']}): Requirement {event['req_id']} updated with: {event['clarification']} (v{event['version']}).")
            elif event["type"] == "override":
                sections.append(f"Override (Step {event['step']}): {event['override_desc']}.")
            elif event["type"] == "new":
                sections.append(f"New Requirement (Step {event['step']}): {event['req_id']} - {event['description']}.")
            elif event["type"] == "discussion":
                sections.append(f"Discussion (Step {event['step']}): {event['content']}.")
            sections.append("")
        
        sections.append("End of Document")
        return "\n".join(sections)

    def get_question(self):
        req_ids = list(self.current_state.keys())
        target_req = self.rng.choice(req_ids)
        return f"What is the current status and full description of requirement {target_req}?"

    def get_answer(self):
        req_ids = list(self.current_state.keys())
        target_req = self.rng.choice(req_ids)
        req = self.current_state[target_req]
        return {
            "req_id": target_req,
            "status": req["status"],
            "description": req["description"]
        }

    def get_meta(self):
        return {
            "num_initial_reqs": len(self.requirements),
            "num_events": len(self.events),
            "num_current_reqs": len(self.current_state)
        }

def generate(seed: int, size: str) -> dict:
    if size not in {"small", "medium", "large"}:
        raise ValueError("size must be 'small', 'medium', or 'large'")
    gen = ProjectSpecGenerator(seed, size)
    return {
        "context": gen._generate_context(),
        "question": gen.get_question(),
        "answer": gen.get_answer(),
        "meta": gen.get_meta()
    }

def score(answer_text: str, truth: dict) -> float:
    if not isinstance(answer_text, str):
        return 0.0

    req_id = truth["req_id"]
    expected_status = truth["status"].lower()
    expected_desc = truth["description"].lower()

    if req_id not in answer_text:
        return 0.0

    status_found = False
    desc_found = False

    # Accept both "Status: pending" (formatted) and "'status': 'pending'" (str(dict)).
    status_pattern = re.compile(
        rf"(?:status[:\s']+|['\"]\s*status\s*['\"]?\s*[:=]\s*['\"])\s*({re.escape(expected_status)})",
        re.IGNORECASE,
    )
    if status_pattern.search(answer_text):
        status_found = True

    desc_pattern = re.compile(rf"({re.escape(expected_desc)})", re.IGNORECASE)
    if desc_pattern.search(answer_text):
        desc_found = True

    if status_found and desc_found:
        return 1.0
    elif status_found or desc_found:
        return 0.5
    return 0.0

if __name__ == "__main__":
    for size in ["small", "medium", "large"]:
        data = generate(0, size)
        print(f"Size: {size}")
        print(f"Context length: {len(data['context']):,} characters")
        print(f"Question: {data['question']}")
        print(f"Truth: {data['answer']}")
        print(f"Meta: {data['meta']}")
        print()
        
        truth_str = f"Requirement {data['answer']['req_id']}: Status: {data['answer']['status']}, Description: {data['answer']['description']}"
        assert score(truth_str, data["answer"]) == 1.0
        
        wrong_status = "Completed" if data["answer"]["status"] != "Completed" else "Pending"
        wrong_answer1 = f"Requirement {data['answer']['req_id']}: Status: {wrong_status}, Description: {data['answer']['description']}"
        assert score(wrong_answer1, data["answer"]) < 1.0
        
        wrong_desc = "This is an incorrect description"
        wrong_answer2 = f"Requirement {data['answer']['req_id']}: Status: {data['answer']['status']}, Description: {wrong_desc}"
        assert score(wrong_answer2, data["answer"]) < 1.0
        
        print("All tests passed for", size)
        print("-" * 50)

```
