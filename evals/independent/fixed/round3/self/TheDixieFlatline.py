import random
import re

ALL_LOCATIONS = [f"Room {i}" for i in range(101, 150)] + [
    "The Vault", "Datacenter Alpha", "Datacenter Beta", "Offsite Storage",
    "Basement Level 1", "Executive Suite", "The Annex", "Server Room C"
]

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
    
    locations = list(ALL_LOCATIONS)

    rng.shuffle(names)
    rng.shuffle(locations)

    def get_new_alias():
        adjs = ["Red", "Blue", "Black", "Omega", "Alpha", "Ghost", "Null", "Void", "Iron", "Stone"]
        nouns = ["Protocol", "Drive", "Archive", "Payload", "Key", "Matrix", "Core", "Box", "File"]
        return f"The {rng.choice(adjs)} {rng.choice(nouns)} {rng.randint(10, 99)}"

    target_original_name = "The Genesis Drive"
    current_alias = target_original_name
    current_holder = rng.choice(names)

    person_to_loc = {n: locations[i % len(locations)] for i, n in enumerate(names)}
    rng.shuffle(locations)
    role_to_person = {r: names[i % len(names)] for i, r in enumerate(roles)}

    signal_indices = sorted(rng.sample(range(0, num_messages), num_signals))
    signal_set = set(signal_indices)

    messages = []
    timestamp = 1672531200 

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
                
                msg1_header = f"Message-ID: <{i:06d}a@corp.local>\nDate: {timestamp}"
                msg1 = f"From: {current_holder}\nTo: {fake_holder}\nSubject: Handing over\n\nI gave '{current_alias}' to you just now."
                messages.append(f"{msg1_header}\n{msg1}")
                
                timestamp += 60 
                msg_header = f"Message-ID: <{i:06d}b@corp.local>\nDate: {timestamp}"
                body = f"From: {current_holder}\nTo: All\nSubject: CORRECTION: Handing over\n\nDisregard my previous message! Typo in the address book. I actually gave '{current_alias}' to {new_holder}."
                current_holder = new_holder

            messages.append(f"{msg_header}\n{body}")

        else:
            n1, n2, n3 = rng.sample(names, 3)
            loc = rng.choice(locations)
            role = rng.choice(roles)
            fake_asset = rng.choice(fake_assets)
            template = rng.choice(noise_templates)
            body = template.format(n1=n1, n2=n2, n3=n3, loc=loc, role=role, fake_asset=fake_asset)
            messages.append(f"{msg_header}\n{body}")

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


def score(answer_text: str, truth: str) -> float:
    def norm(text):
        t = str(text).lower()
        t = re.sub(r'[^\w\s]', '', t)
        return " ".join(t.split())
        
    ans_clean = norm(answer_text)
    tru_clean = norm(truth)
    
    mentioned = set()
    for loc in ALL_LOCATIONS:
        loc_clean = norm(loc)
        loc_no_the = re.sub(r'^the\s+', '', loc_clean)
        pattern = r'\b' + re.escape(loc_no_the) + r'\b'
        if re.search(pattern, ans_clean):
            mentioned.add(loc)
            
    truth_matched = False
    for m in mentioned:
        if norm(m) == tru_clean:
            truth_matched = True
            break
            
    if not truth_matched:
        return 0.0
        
    if len(mentioned) > 1:
        return 0.0
        
    return 1.0


if __name__ == "__main__":
    for sz in ["small", "medium", "large"]:
        data = generate(seed=0, size=sz)
        print(f"--- Size: {sz.upper()} ---")
        print(f"Context Length: {len(data['context'])} characters")
        print(f"Question: {data['question']}")
        print(f"Truth: {data['answer']}")
        print(f"Meta: {data['meta']}")
        print()

    print("Running self-tests for scorer formats and hedges across seeds 0-4...")
    for s in range(5):
        d = generate(seed=s, size="small")
        truth = d['answer']
        
        # Valid Formats
        assert score(truth, truth) == 1.0
        assert score(f"The answer is {truth}.", truth) == 1.0
        assert score(f"**{truth}**", truth) == 1.0
        assert score(f"- {truth}", truth) == 1.0
        assert score(f"JSON: {{'answer': '{truth}'}}", truth) == 1.0
        assert score(f"{truth.upper()}", truth) == 1.0
        assert score(f"{truth.lower()}", truth) == 1.0
        assert score(f"  {truth}  \n", truth) == 1.0
        assert score(f"I am pretty sure it is located in {truth}, yes.", truth) == 1.0
        
        # Handling the definite article organically 
        if truth.lower().startswith("the "):
            truth_no_the = truth[4:]
            assert score(truth_no_the, truth) == 1.0
            
        # Hedges and multiple candidates
        other_loc = "Room 101" if truth != "Room 101" else "Room 102"
        assert score(f"{truth} or {other_loc}", truth) == 0.0
        assert score(f"moved from {other_loc} to {truth}", truth) == 0.0
        assert score(f"not {other_loc}, it is {truth}", truth) == 0.0
        assert score("Totally Wrong Location", truth) == 0.0
        assert score(other_loc, truth) == 0.0

    print("Running self-tests to verify final locations exist in context...")
    for sz in ["small", "medium", "large"]:
        for s in range(5):
            d = generate(seed=s, size=sz)
            assert d['answer'] in d['context'], f"Defect: Answer {d['answer']} missing from context (seed {s}, size {sz})"
    print("All self-tests passed.")

