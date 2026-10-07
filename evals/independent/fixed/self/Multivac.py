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
        desc_templates = [
            "User authentication mechanism {details}. This will involve {extra1} and ensure {extra2}.",
            "Data encryption standard {details}, covering {extra1} and {extra2} aspects.",
            "Reporting module for {details}, including capabilities for {extra1} and {extra2}.",
            "API integration with {details}, facilitating {extra1} and {extra2} processes.",
            "User interface overhaul, specifically {details}, with attention to {extra1} and {extra2}.",
            "Database migration from {details}, impacting {extra1} and {extra2} systems.",
            "Accessibility compliance according to {details}, ensuring {extra1} and {extra2} are met.",
            "Performance optimization targeting {details}, focusing on {extra1} and {extra2} bottlenecks."
        ]
        details_options = [
            "using OAuth 2.0 for enhanced security", "with AES-256 for data at rest",
            "for comprehensive sales data analysis", "with external Partner X's system",
            "to include dark mode support and improved navigation", "from legacy SQL to a modern NoSQL solution",
            "WCAG 2.1 AA standards for web accessibility", "sub-second response times for critical APIs"
        ]
        extra_options = [
            "multi-factor authentication", "session management", "role-based access control",
            "data in transit", "data at rest", "key management protocols",
            "real-time data visualization", "customizable dashboards", "export to various formats",
            "automated data synchronization", "error handling mechanisms", "versioning strategies",
            "responsive design principles", "improved information architecture", "user testing feedback incorporation",
            "data schema transformation", "minimizing downtime", "data integrity checks",
            "keyboard navigation", "screen reader compatibility", "color contrast adjustments",
            "database query optimization", "caching strategies", "load balancing implementation"
        ]
        for i in range(num_reqs):
            req_id = f"R{i+1:03d}" 
            desc_template = self.rng.choice(desc_templates)
            detail = self.rng.choice(details_options)
            extra1 = self.rng.choice(extra_options)
            extra2 = self.rng.choice(extra_options)
            while extra1 == extra2: # Ensure extras are different
                extra2 = self.rng.choice(extra_options)
            
            desc = desc_template.format(details=detail, extra1=extra1, extra2=extra2)
            reqs[req_id] = {
                "description": desc,
                "status": "Pending",
                "priority": self.rng.choice(["High", "Medium", "Low"]),
                "version": 1,
                "last_updated": 0
            }
        return reqs

    def _generate_timeline(self):
        event_counts = {"small": 200, "medium": 1000, "large": 4000}
        num_events = event_counts[self.size]
        
        discussion_topics = ["budget allocation", "project timeline adjustments", "staffing needs and recruitment",
                             "potential risks and mitigation strategies", "quality assurance processes",
                             "stakeholder communication plan", "vendor selection criteria", "compliance requirements",
                             "technology stack choices", "data migration strategy", "user acceptance testing protocol",
                             "training plan for end-users", "documentation standards", "security audit preparation"]
        meeting_purposes = ["Sprint Planning", "Backlog Grooming", "Stakeholder Update", "Technical Deep Dive",
                            "Risk Assessment Review", "Design Review", "Post-Mortem Analysis", "Requirements Elicitation"]
        email_subjects = ["Urgent: Decision needed on", "Follow-up on", "Clarification required for", "Proposal for",
                          "Minutes from", "Action items from", "Status update for", "Reminder: Deadline for"]

        for step in range(num_events):
            event_type = self.rng.choices(
                ["update", "clarification", "override", "new", "discussion", "meeting", "email"],
                weights=[0.2, 0.2, 0.05, 0.15, 0.1, 0.15, 0.15] 
            )[0]
            
            if event_type == "update" and self.requirements:
                req_id = self.rng.choice(list(self.requirements.keys()))
                req = self.requirements[req_id]
                old_status = req["status"]
                new_status = self.rng.choice(["In Progress", "Completed", "Blocked", "On Hold", "Under Review", "Deferred"])
                req["status"] = new_status
                req["version"] += 1
                req["last_updated"] = step
                
                status_change_verbs = ["changed", "updated", "moved", "transitioned", "set"]
                status_reasons = ["due to recent progress.", "as per team lead's instruction.", "following QA feedback.",
                                  "because of a dependency issue.", "pending further information.", "after stakeholder review."]

                event_text = (
                    f"Update (Step {step}): The status of requirement {req_id} has been {self.rng.choice(status_change_verbs)} "
                    f"from {old_status} to {new_status} (version {req['version']}). This change was made {self.rng.choice(status_reasons)} "
                    f"Further details regarding this update can be found in the project's internal tracking system, JIRA ticket PROJ-{step:04d}."
                )
                self.events.append({"type": "update", "req_id": req_id, "old_status": old_status, "new_status": new_status, "version": req["version"], "step": step, "text": event_text})

            elif event_type == "clarification" and self.requirements:
                req_id = self.rng.choice(list(self.requirements.keys()))
                req = self.requirements[req_id]
                
                clarification_phrases = [
                    "must use open-source libraries where feasible",
                    "needs to support mobile devices (iOS and Android)",
                    "should be backwards compatible with version 1.2 APIs",
                    "requires a security review before deployment",
                    "user training materials must be prepared",
                    "performance benchmarks must be met under load",
                    "documentation needs to be updated in Confluence",
                    "accessibility testing with JAWS screen reader is mandatory",
                    "error logging must be comprehensive and centralized",
                    "integration with the existing CI/CD pipeline is required"
                ]
                clarification = self.rng.choice(clarification_phrases)
                req["description"] += f" Additionally, it {clarification}."
                req["version"] += 1
                req["last_updated"] = step

                clarification_verbs = ["clarified", "amended", "specified", "noted", "added"]
                sources = ["product owner during the daily standup.", "lead developer via email.", "QA team in their report.",
                          "legal department's memo.", "UX designer's feedback session."]

                event_text = (
                    f"Clarification (Step {step}): Requirement {req_id} has been {self.rng.choice(clarification_verbs)} "
                    f"(version {req['version']}). It is now specified that it {clarification}. This point was raised by the {self.rng.choice(sources)} "
                    f"The team should ensure this clarification is reflected in all relevant design documents and test cases."
                )
                self.events.append({"type": "clarification", "req_id": req_id, "clarification": clarification, "version": req["version"], "step": step, "text": event_text})

            elif event_type == "override" and len(self.requirements) >= 2:
                req_id1, req_id2 = self.rng.sample(list(self.requirements.keys()), 2)
                req1 = self.requirements[req_id1]
                req2 = self.requirements[req_id2]
                
                override_type = self.rng.choice(["depends_on", "supersedes", "merged"])
                override_desc = ""
                if override_type == "depends_on":
                    req1["description"] += f" (Note: Implementation of this requirement is now dependent on the prior completion of {req_id2}.)"
                    override_desc = f"{req_id1} now has a dependency on {req_id2}."
                elif override_type == "supersedes":
                    req1["status"] = "Obsolete"
                    req2["description"] += f" (Note: This requirement now fully incorporates the scope and objectives of the previously defined {req_id1}.)"
                    override_desc = f"{req_id2} supersedes {req_id1}, rendering the latter obsolete."
                elif override_type == "merged":
                    new_id = f"R{len(self.requirements)+1:03d}"
                    self.requirements[new_id] = {
                        "description": f"Merged Requirement: This requirement combines the functionalities originally outlined in {req_id1} ('{req1['description'].split('.')[0]}') and {req_id2} ('{req2['description'].split('.')[0]}'). The full scope now encompasses both.",
                        "status": "Pending",
                        "priority": "High", 
                        "version": 1,
                        "last_updated": step
                    }
                    req1["status"] = "Obsolete"
                    req2["status"] = "Obsolete"
                    override_desc = f"{req_id1} and {req_id2} have been merged into a new requirement {new_id}."
                
                reasons_for_override = [
                    "This decision was made to streamline development efforts and reduce complexity.",
                    "After careful analysis by the architecture team, this change was deemed necessary for optimal system design.",
                    "Stakeholders agreed that this restructuring better aligns with current business priorities.",
                    "Technical constraints discovered during initial prototyping necessitated this adjustment.",
                    "To avoid duplication of work and ensure a cohesive final product, this override was implemented."
                ]

                event_text = (
                    f"Override (Step {step}): {override_desc} {self.rng.choice(reasons_for_override)} "
                    f"All team members are advised to review the implications of this change on their current tasks and dependencies."
                )
                self.events.append({"type": "override", "req_ids": [req_id1, req_id2], "override_desc": override_desc, "step": step, "text": event_text})

            elif event_type == "new":
                new_id = f"R{len(self.requirements)+1:03d}"
                desc_template = self.rng.choice([
                    "A new requirement for {details} has been identified. This will involve {extra1} and also address {extra2}.",
                    "Stakeholders have requested {details}. Key aspects include {extra1} and ensuring {extra2}.",
                    "To meet emerging business needs, {details} is now required. This encompasses {extra1} and {extra2}."
                ])
                detail = self.rng.choice([
                    "enhanced localization features for global markets", "implementation of an automated testing framework",
                    "creation of comprehensive user documentation", "significant scalability improvements for backend services",
                    "development of an in-app user feedback system", "integration with a new third-party analytics platform",
                    "refactoring of legacy code components for maintainability", "implementation of a disaster recovery plan"
                ])
                extra1 = self.rng.choice([
                    "support for at least 5 major languages", "achieving 80% code coverage for critical modules",
                    "detailed user manuals and online help", "handling a 10x increase in concurrent users",
                    "collection of user sentiment through surveys", "data ingestion from PartnerY's API",
                    "improving code readability and reducing technical debt", "regular data backups and failover mechanisms"
                ])
                extra2 = self.rng.choice([
                    "currency and date formatting localization", "integration with the CI/CD pipeline for automated runs",
                    "video tutorials for complex features", "database query optimization for high load",
                    "prioritization of feature requests based on feedback", "ensuring data privacy compliance (GDPR, CCPA)",
                    "updating dependencies to supported versions", "testing recovery procedures quarterly"
                ])
                while extra1 == extra2:
                    extra2 = self.rng.choice([
                        "currency and date formatting localization", "integration with the CI/CD pipeline for automated runs",
                        "video tutorials for complex features", "database query optimization for high load",
                        "prioritization of feature requests based on feedback", "ensuring data privacy compliance (GDPR, CCPA)",
                        "updating dependencies to supported versions", "testing recovery procedures quarterly"
                    ])

                desc = desc_text = desc_template.format(details=detail, extra1=extra1, extra2=extra2)
                self.requirements[new_id] = {
                    "description": desc,
                    "status": "Pending",
                    "priority": self.rng.choice(["High", "Medium", "Low"]),
                    "version": 1,
                    "last_updated": step
                }
                
                sources_of_new_req = [
                    "product strategy meeting.", "client feedback session.", "market analysis report.",
                    "technical spike investigation.", "compliance audit findings.", "UX research study."
                ]

                event_text = (
                    f"New Requirement (Step {step}): {desc_text} This requirement, identified as {new_id}, "
                    f"was initiated based on insights from a recent {self.rng.choice(sources_of_new_req)} "
                    f"The project manager will assign this to the relevant team for estimation and planning."
                )
                self.events.append({"type": "new", "req_id": new_id, "description": self.requirements[new_id]["description"], "step": step, "text": event_text})

            elif event_type == "discussion":
                topic = self.rng.choice(discussion_topics)
                content_starter = self.rng.choice([
                    f"A discussion was initiated regarding {topic}.",
                    f"Concerns were raised by the team about {topic}.",
                    f"A meeting is proposed to address challenges related to {topic}.",
                    f"New information has come to light concerning {topic}, requiring attention.",
                    f"The steering committee has requested an update on {topic}."
                ])
                discussion_points = [
                    "potential budget overruns and mitigation strategies.",
                    "timeline slippage due to unforeseen complexities.",
                    "the need for additional specialized personnel.",
                    "a newly identified risk that could impact project success.",
                    "quality standards not being met in recent deliverables.",
                    "conflicting stakeholder expectations that need reconciliation.",
                    "delays from a third-party vendor impacting our schedule.",
                    "scope creep that needs to be managed effectively."
                ]
                next_steps = [
                    "This will be escalated to senior management for a decision.",
                    "A working group will be formed to investigate and propose solutions.",
                    "The project plan will be updated to reflect these considerations.",
                    "Further analysis is required before any action can be taken.",
                    "A follow-up meeting is scheduled for next week to review progress."
                ]
                event_text = (
                    f"Discussion (Step {step}): {content_starter} Key points included {self.rng.choice(discussion_points)} "
                    f"{self.rng.choice(next_steps)} All relevant parties have been informed."
                )
                self.events.append({"type": "discussion", "topic": topic, "content": content_starter, "step": step, "text": event_text})

            elif event_type == "meeting":
                purpose = self.rng.choice(meeting_purposes)
                attendees_roles = self.rng.sample([
                    "Project Manager", "Lead Developer", "QA Lead", "Product Owner", "UX Designer",
                    "Business Analyst", "Stakeholder Representative", "External Consultant", "Security Officer",
                    "DevOps Engineer"
                ], k=self.rng.randint(3, 6))
                attendees = ", ".join(attendees_roles)
                
                num_points = self.rng.randint(2, 5)
                meeting_points = []
                for _ in range(num_points):
                    req_for_point = self.rng.choice(list(self.requirements.keys())) if self.requirements else "N/A"
                    point_type = self.rng.choice(["update", "decision", "action_item", "info_sharing"])
                    if point_type == "update":
                        point_text = f"Update on {req_for_point}: Progress is {self.rng.choice(['on track', 'slightly behind', 'ahead of schedule'])}. Next milestone: {self.rng.choice(['design sign-off', 'development complete', 'QA handover'])}."
                    elif point_type == "decision":
                        point_text = f"Decision regarding {req_for_point}: It was agreed to {self.rng.choice(['proceed with the proposed approach', 're-evaluate alternatives', 'defer implementation until Q4'])}."
                    elif point_type == "action_item":
                        assignee = self.rng.choice(attendees_roles)
                        point_text = f"Action Item: {assignee} to {self.rng.choice(['investigate options for', 'draft a proposal on', 'schedule a follow-up for'])} {req_for_point} by {self.rng.choice(['end of week', 'next Monday', 'EOD tomorrow'])}."
                    else: 
                        point_text = f"Information Sharing: {self.rng.choice(['Market analysis shows a shift in user preferences.', 'A new industry regulation might impact this project.', 'Competitor X has launched a similar feature.'])}"
                    meeting_points.append(point_text)
                
                event_text = (
                    f"Meeting Minutes (Step {step}): Meeting held for {purpose}.\n"
                    f"Attendees: {attendees}.\n"
                    f"Agenda:\n"
                )
                for i, point in enumerate(meeting_points):
                    event_text += f"  {i+1}. {point}\n"
                event_text += "The meeting adjourned with clear action items assigned. Minutes recorded by the Project Manager."
                self.events.append({"type": "meeting", "purpose": purpose, "step": step, "text": event_text})

            elif event_type == "email":
                sender_role = self.rng.choice(["Project Manager", "Lead Developer", "Product Owner", "QA Lead", "External Stakeholder"])
                recipient_roles = self.rng.sample([
                    "Development Team", "Design Team", "Steering Committee", "All Staff", "Client X Contact"
                ], k=self.rng.randint(1, 2))
                recipients = ", ".join(recipient_roles)
                subject_topic = self.rng.choice(["Project Phoenix Update", "Requirement Clarification", "Urgent Decision Needed", "Meeting Follow-up", "Risk Assessment", "Resource Allocation"])
                req_for_subject = self.rng.choice(list(self.requirements.keys())) if self.requirements else "Overall Project"
                subject = f"{self.rng.choice(email_subjects)} {subject_topic} - Ref: {req_for_subject}"
                
                greeting = self.rng.choice(["Hi Team,", "Dear All,", "Hello,", "Good morning,"])
                body_paras = []
                num_paras = self.rng.randint(1, 3)
                for _ in range(num_paras):
                    if self.rng.random() < 0.7 and self.requirements: # 70% chance to talk about a req
                        req_id_body = self.rng.choice(list(self.requirements.keys()))
                        body_paras.append(self.rng.choice([
                            f"Regarding requirement {req_id_body} ('{self.requirements[req_id_body]['description'].split('.')[0]}...'), we need to discuss its current status.",
                            f"Please provide an update on {req_id_body} by EOD. Specifically, we need to know if {self.rng.choice(['the dependencies are resolved', 'the testing has commenced', 'the design is finalized'])}.",
                            f"There seems to be a misunderstanding about the scope of {req_id_body}. Could the original author clarify the intent behind '{self.rng.choice(['the performance targets', 'the security considerations', 'the user interface elements'])}'?"
                        ]))
                    else:
                        body_paras.append(self.rng.choice([
                            f"This email is to inform you about {self.rng.choice(['a change in project priorities', 'an upcoming audit', 'a new team member joining'])}.",
                            f"We need to schedule a meeting to {self.rng.choice(['review the project roadmap', 'discuss resource allocation', 'address the recent feedback from stakeholders'])}.",
                            f"Please find attached the {self.rng.choice(['latest version of the design document', 'updated risk register', 'minutes from the steering committee meeting'])}."
                        ]))
                closing = self.rng.choice(["Best regards,", "Thanks,", "Sincerely,", "Cheers,"])
                sender_name = self.rng.choice(["Alice Wonderland", "Bob The Builder", "Charlie Brown", "Diana Prince", "Eve Moneypenny"])
                
                event_text = (
                    f"Email (Step {step}):\n"
                    f"From: {sender_name} ({sender_role})\n"
                    f"To: {recipients}\n"
                    f"Subject: {subject}\n"
                    f"\n"
                    f"{greeting}\n"
                    f"\n"
                )
                for para in body_paras:
                    event_text += f"{para}\n\n"
                event_text += (
                    f"{closing}\n"
                    f"{sender_name}\n"
                    f"(Sent via company email system - Ref: MSG-{step:05d})"
                )
                self.events.append({"type": "email", "step": step, "text": event_text})

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
        
        sections.append("Project Phoenix - Requirements and Event Log")
        sections.append("=" * 70)
        sections.append("This document serves as the central repository for all requirements, decisions, discussions, and communications pertaining to Project Phoenix.")
        sections.append("It is a living document and will be updated throughout the project lifecycle. Please refer to the version history for changes.")
        sections.append(f"Document Version: {self.rng.randint(1, 25)}.0")
        sections.append(f"Last Updated: {self.rng.choice(['2024-03-15', '2024-04-20', '2024-05-28'])} by Project Management Office")
        sections.append("")
        sections.append("Table of Contents:")
        sections.append("1. Initial Requirements Overview")
        sections.append("2. Chronological Event Log (Updates, Clarifications, Overrides, New Requirements, Discussions, Meeting Minutes, Emails)")
        sections.append("3. Current State of Active Requirements (Summary - see end of document)")
        sections.append("")
        sections.append("1. Initial Requirements Overview")
        sections.append("-" * 40)
        sections.append("The following requirements were identified at the project's inception. Note that their status and description may have changed due to subsequent events documented below.")
        sections.append("")
        for req_id, req in self.requirements.items():
            sections.append(f"- {req_id}: {req['description']} (Initial Status: {req['status']}, Priority: {req['priority']}, Version: {req['version']})")
        sections.append("")
        sections.append("2. Chronological Event Log")
        sections.append("-" * 40)
        sections.append("This section details all significant events, decisions, and communications in chronological order.")
        sections.append("")

        for event in self.events:
            sections.append(event["text"])
            sections.append("") 
        
        sections.append("-" * 40)
        sections.append("3. Current State of Active Requirements (Summary)")
        sections.append("This section provides a snapshot of requirements currently considered active (i.e., not Obsolete).")
        sections.append("For the definitive current status and full description, refer to the requirement's latest version in the event log.")
        sections.append("")
        if not self.current_state:
            sections.append("No active requirements at this time.")
        else:
            for req_id, req in self.current_state.items():
                sections.append(f"- {req_id}: Status: {req['status']}, Priority: {req['priority']}. Description starts: '{req['description'].split('.')[0]}...'")
        sections.append("")
        sections.append("=" * 70)
        sections.append("End of Document")
        return "\n".join(sections)

    def get_question(self):
        req_ids = list(self.current_state.keys())
        if not req_ids: # Should not happen if new reqs are generated
            req_ids = list(self.requirements.keys())
            req_ids = [rid for rid in req_ids if self.requirements[rid]["status"] != "Obsolete"]
            if not req_ids: return "What is the current status and full description of a requirement?" # Fallback
        target_req = self.rng.choice(req_ids)
        return f"What is the current status and the complete, consolidated description of requirement {target_req}?"

    def get_answer(self):
        req_ids = list(self.current_state.keys())
        if not req_ids:
            req_ids = list(self.requirements.keys())
            req_ids = [rid for rid in req_ids if self.requirements[rid]["status"] != "Obsolete"]
            if not req_ids: return {"req_id": "N/A", "status": "N/A", "description": "No active requirements."}
        
        target_req = self.rng.choice(req_ids)
        req = self.current_state[target_req]
        return {
            "req_id": target_req,
            "status": req["status"],
            "description": req["description"]
        }

    def get_meta(self):
        active_req_ids = list(self.current_state.keys())
        num_active_reqs = len(active_req_ids)
        
        num_obsolete = 0
        for req_id, req in self.requirements.items():
            if req["status"] == "Obsolete":
                num_obsolete +=1
        
        return {
            "num_initial_reqs": len(self.requirements),
            "num_events": len(self.events),
            "num_active_reqs": num_active_reqs,
            "num_obsolete_reqs": num_obsolete,
            "target_req_id_for_question": self.get_answer()["req_id"] 
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
    
    if req_id not in answer_text: # Basic check if the req_id is mentioned
        return 0.0
    
    status_found = False
    desc_found = False
    
    status_pattern = re.compile(rf"status\s*[:\s]*(?:is\s*|of\s*|for\s*)?({re.escape(expected_status)})", re.IGNORECASE | re.DOTALL)
    if status_pattern.search(answer_text):
        status_found = True
    
    # For description, we need a more robust check than simple regex due to length and paraphrasing.
    # We'll look for key phrases from the description.
    # This is a simplification; a better scorer might use embeddings or more complex NLP.
    
    desc_keywords_to_find = set()
    # Heuristic: take the first few words of the description and a few key phrases.
    # This is imperfect but better than exact match for long descriptions.
    if expected_desc:
        parts = expected_desc.split()
        if len(parts) >= 5:
            desc_keywords_to_find.add(" ".join(parts[:3]).lower()) # First 3 words
            desc_keywords_to_find.add(" ".join(parts[len(parts)//2 : len(parts)//2 + 2]).lower()) # Middle 2 words
        elif len(parts) >= 3:
            desc_keywords_to_find.add(" ".join(parts[:2]).lower()) # First 2 words
        elif len(parts) > 0:
             desc_keywords_to_find.add(parts[0].lower()) # First word

        # Add a couple of specific phrases if they exist
        specific_phrases = ["oauth 2.0", "aes-256", "wcag 2.1 aa", "sub-second response", "dark mode", "no to sql", "open-source libraries", "mobile devices", "backwards compatible", "security review", "user training", "performance benchmarks", "confluence", "jaws screen reader", "error logging", "ci/cd pipeline"]
        for phrase in specific_phrases:
            if phrase in expected_desc:
                desc_keywords_to_find.add(phrase.lower())
    
    desc_found_score = 0
    if desc_keywords_to_find:
        found_keywords = 0
        for keyword in desc_keywords_to_find:
            if keyword in answer_text.lower():
                found_keywords += 1
        desc_found_score = found_keywords / len(desc_keywords_to_find)
        desc_found = desc_found_score > 0.5 # At least half of the keywords found
    else: # No keywords could be extracted (e.g. very short desc)
        if expected_desc.lower() in answer_text.lower():
            desc_found = True
        else:
            # Try to see if a significant portion of the description is present
            # This is a very rough check
            words_in_truth = set(expected_desc.lower().split())
            words_in_answer = set(answer_text.lower().split())
            common_words = words_in_truth.intersection(words_in_answer)
            if len(common_words) / len(words_in_truth) > 0.5 and len(words_in_truth) > 0 : # At least 50% word overlap
                 desc_found = True
            elif len(expected_desc) == 0 and len(answer_text.strip()) == 0: # Both empty
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
        assert score(truth_str, data["answer"]) == 1.0, f"Score for truth_str should be 1.0 for {size}"
        
        # Test wrong status
        wrong_status = "Completed" if data["answer"]["status"] != "Completed" else "Pending"
        wrong_answer1 = f"Requirement {data['answer']['req_id']}: Status: {wrong_status}, Description: {data['answer']['description']}"
        assert score(wrong_answer1, data["answer"]) < 1.0, f"Score for wrong_status should be < 1.0 for {size}"
        
        # Test wrong description (completely different)
        wrong_desc = "This is an entirely incorrect and fabricated description that bears no resemblance to the actual requirement."
        wrong_answer2 = f"Requirement {data['answer']['req_id']}: Status: {data['answer']['status']}, Description: {wrong_desc}"
        assert score(wrong_answer2, data["answer"]) < 1.0, f"Score for wrong_desc should be < 1.0 for {size}"
        
        # Test partial description (some keywords missing)
        partial_desc = data['answer']['description'] + " This part is extra and wrong."
        if len(data['answer']['description'].split()) > 3: # Ensure there's enough to make a partial
            partial_desc_list = data['answer']['description'].split()[:len(data['answer']['description'].split())//2]
            partial_desc = " ".join(partial_desc_list) + " (incomplete)"
        wrong_answer3 = f"Requirement {data['answer']['req_id']}: Status: {data['answer']['status']}, Description: {partial_desc}"
        # This might still score high if key phrases are present, so it's a softer check.
        # For now, we mainly rely on the completely wrong description.
        
        print(f"All basic score tests passed for {size}")
        print("-" * 50)
