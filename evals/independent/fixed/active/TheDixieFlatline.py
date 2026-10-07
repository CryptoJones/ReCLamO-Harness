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

    timestamp = 1672531200 # Jan 1 2023
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
                messages.append(f"{msg_header}a\n{msg1}")
                
                timestamp += 60 
                msg_header = f"Message-ID: <{i:06d}b@corp.local>\nDate: {timestamp}"
                body = f"From: {current_holder}\nTo: All\nSubject: CORRECTION: Handing over\n\nDisregard my previous message! Typo in the address book. I actually gave '{current_alias}' to {new_holder}."
                current_holder = new_holder

            if action != "correction":
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


def score(answer_text: str, truth: str) -> float:
    ans_clean = re.sub(r'[^\w\s]', '', answer_text.lower())
    tru_clean = re.sub(r'[^\w\s]', '', truth.lower())

    pattern = r'\b' + re.escape(tru_clean) + r'\b'
    if re.search(pattern, ans_clean):
        # Penalize if they just dumped a huge chunk of text hoping to catch the answer
        if len(ans_clean) > len(tru_clean) + 50:
            return 0.5
        return 1.0
    return 0.0


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
        assert score(f"{truth} but with lots of extra text to trigger the penalty " * 3, truth) == 0.5
        assert score("Totally Wrong Location", truth) == 0.0
