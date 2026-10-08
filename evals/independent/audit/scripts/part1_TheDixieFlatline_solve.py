"""Text-only solver for TheDixieFlatline + ambiguity-trigger counter.

Parses the CONTEXT TEXT only (no generator internals) and applies the reading a careful
human would: setup roles/offices, approved relocations, personnel changes, custody
transfers (direct, desk-of-role, correction overrides). Then compares with the key and
flags situations where a reasonable reader could defend a different answer:
  - HOLDER_MOVED_AFTER_DESK: asset left on a role's desk, then that person relocates
    (does the asset follow the person or stay at the old desk?)
  - ROLE_REASSIGNED_AFTER_DESK: asset left on "the desk of the <role>", then a new person
    takes over that role (is it now with the new role holder?)
  - NO_CUSTODY_EVENT: the starting holder is never named.
Usage: python3 -I part1_TheDixieFlatline_solve.py <generator.py> <size> <seed_from> <seed_to>
"""
import importlib.util, re, sys


def solve(ctx):
    msgs = re.split(r"\n\n(?=Message-ID: )", ctx)
    loc, role, alias = {}, {}, "The Genesis Drive"
    holder, desk_role, flags, events = None, None, set(), 0
    for m in msgs:
        h = dict(re.findall(r"^(From|To|Subject): (.*)$", m, re.M))
        body = m.split("\n\n", 1)[1] if "\n\n" in m else ""
        s = h.get("Subject", "")
        if s in ("Welcome", "Directory update", "Network hookup"):
            loc[h["To"]] = re.search(r"(?:office is|listed in|workspace at) (.+?)\.", body).group(1)
        elif s == "Organization Chart":
            p, r = re.search(r"that (\w+) is our (.+)\.", body).groups(); role[r] = p
        elif s == "Role Confirmation":
            r, p = re.search(r"all (.+) inquiries to (\w+)\.", body).groups(); role[r] = p
        elif s == "Introduction":
            role[re.search(r"your (.+)\.", body).group(1)] = h["From"]
        elif s == "Personnel Change":
            p, r = re.search(r"welcome (\w+), who is taking over as the new (.+) starting", body).groups()
            if desk_role == r and holder != p:
                flags.add("ROLE_REASSIGNED_AFTER_DESK")
            role[r] = p
        elif s == "Office Relocation":
            p, l = re.search(r"approved\. (\w+), please move your things to (.+) by EOD", body).groups()
            if desk_role and p == holder and loc.get(p) != l:
                flags.add("HOLDER_MOVED_AFTER_DESK")
            loc[p] = l
        elif s == "Codename Update":
            old, new = re.search(r"'(.+)' will now be known as '(.+)'", body).groups()
            if old == alias:
                alias = new
        elif s == "Custody Transfer":
            events += 1
            if "physically handed" in body:
                holder, desk_role = h["To"], None
            else:
                r = re.search(r"desk of the (.+)\.", body).group(1)
                holder, desk_role = role[r], r
        elif s == "CORRECTION: Handing over":
            events += 1
            holder, desk_role = re.search(r"actually gave '.+' to (\w+)\.", body).group(1), None
    if events == 0:
        flags.add("NO_CUSTODY_EVENT")
    return (loc.get(holder) if holder else None), holder, sorted(flags)


if __name__ == "__main__":
    path, size, a, b = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    spec = importlib.util.spec_from_file_location("g", path); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    agree = 0
    for seed in range(a, b):
        d = g.generate(seed, size)
        ans, holder, flags = solve(d["context"])
        ok = ans == d["answer"]
        agree += ok
        if not ok or flags or seed < 5:
            print(f"seed {seed}: mine={ans!r} key={d['answer']!r} holder={holder} keyholder={d['meta']['final_holder']} {'OK' if ok else 'DIFF'} {flags}")
    print(f"{size}: agree {agree}/{b - a}")
